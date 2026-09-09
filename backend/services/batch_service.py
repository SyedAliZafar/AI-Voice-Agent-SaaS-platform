"""Serial, event-chained batch outreach runs.

Replaces the fixed-interval-timer idea with the simpler thing an operator actually
wants: dial one prospect, wait for that call to genuinely end, dial the next. "Genuinely
end" is call_service._fanout_post_call firing with a terminal Call.status — the same
signal lead_service and prospect_service already key off. See
phases/in-progress/serial-batch-calling.md for the full design writeup.

Three functions matter, the rest is plumbing:
  - start_run: pick targets (via prospect_service.batch_call_targets, unchanged), create
    the run + its items, dial the first one.
  - claim_next: the concurrency guard. A single conditional UPDATE ("claim this queued
    item iff it's still queued") is what makes advance_run() safe to call more than once
    for the same run — Postgres serializes the two UPDATEs at the row level under
    READ COMMITTED, so the loser's WHERE re-check sees status already flipped and
    affects zero rows. No explicit locking needed.
  - mark_item_done_and_advance: called from _fanout_post_call. Same shape of guard —
    the UPDATE only succeeds for the first of (call_ended, call_analyzed, reconcile) to
    reach it, so the run advances exactly once per call no matter how many times its
    terminal state is reported.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.models.batch_run import BatchRun, BatchRunItem
from backend.models.call import Call
from backend.models.prospect import Prospect
from backend.services import (
    agent_service,
    call_service,
    prospect_service,
    prospect_variables,
    test_call_service,
)

BATCH_RUN_MAX = 15  # small on purpose — this is the "watch it work" path, not bulk outreach


class BatchRunError(Exception):
    """Raised for setup failures (bad agent, no eligible prospects) — before any call
    is placed, so callers can turn this straight into a 4xx without any cleanup.
    """


def _build_personalized_prompt(agent, prospect: Prospect) -> str:
    """Same assembly as api/prospects.py's _build_personalized_prompt — duplicated
    rather than imported to avoid a service-layer -> router-layer import; if this drifts
    from the other copy, fold both into script_service instead of re-syncing by hand.
    """
    from backend.schemas.prospect import CompanyResearch
    from backend.services import script_service

    research = CompanyResearch.model_validate(prospect.research or {})
    return script_service.build_prospect_prompt(
        agent.system_prompt, prospect.name, research, prospect_notes=prospect.prospect_notes
    )


async def _explicit_targets(
    db: AsyncSession, tenant_id: uuid.UUID, prospect_ids: list[uuid.UUID]
) -> list[Prospect]:
    """The prospects the operator ticked, in the order they ticked them.

    Deliberately does NOT apply batch_call_targets' eligibility filters (never called,
    not opted out, ranked by priority): those exist to *choose* targets when nobody said
    who to call. Here somebody did, and silently dropping a prospect they can see
    selected on screen would be the surprising behaviour. The two exceptions are
    non-negotiable rather than editorial: another tenant's ids (ADR-001 — they read as
    "not found") and prospects with no phone number, which cannot be dialed at all.
    """
    rows = (
        await db.execute(
            select(Prospect).where(
                Prospect.id.in_(prospect_ids),
                Prospect.tenant_id == tenant_id,
                Prospect.phone.isnot(None),
            )
        )
    ).scalars().all()

    by_id = {p.id: p for p in rows}
    return [by_id[pid] for pid in prospect_ids if pid in by_id]


async def start_run(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    agent_id: uuid.UUID | None,
    external_agent_id: str | None,
    limit: int,
    city: str | None,
    max_call_count: int,
    dynamic_variables: dict[str, str],
    prospect_ids: list[uuid.UUID] | None = None,
) -> BatchRun:
    """Select targets, create the run and its queued items, and dial the first one.

    Two ways to say who to call, and `prospect_ids` wins when given: an explicit list the
    operator ticked in the UI, or — when they didn't pick anyone — the same
    filter-and-rank selection POST /batch-call has always used.

    Raises BatchRunError if the agent doesn't resolve or nothing is eligible — both
    checked before any row is written, so a bad request never leaves a half-started run.
    """
    if agent_id:
        agent = await agent_service.get_agent(db, agent_id, tenant_id)
        if not agent:
            raise BatchRunError("Agent not found")

    limit = min(limit, BATCH_RUN_MAX)
    if prospect_ids:
        # Capped on BATCH_RUN_MAX, not `limit`: `limit` means "how many should I pick
        # for you", which is meaningless once the operator has picked. Truncating a
        # 12-prospect selection down to a stale limit of 5 would silently drop seven
        # companies they can see ticked on screen.
        targets = await _explicit_targets(db, tenant_id, prospect_ids[:BATCH_RUN_MAX])
        if not targets:
            raise BatchRunError(
                "None of the selected prospects can be called — they have no phone "
                "number, or no longer exist."
            )
    else:
        targets = await prospect_service.batch_call_targets(
            db, tenant_id, limit=limit, city=city, max_call_count=max_call_count
        )
        if not targets:
            raise BatchRunError("No eligible prospects matched the given filters")

    run = BatchRun(
        tenant_id=tenant_id,
        agent_id=agent_id,
        external_agent_id=external_agent_id,
        status="running",
        dynamic_variables=dynamic_variables,
        total=len(targets),
        started_at=datetime.now(UTC),
    )
    db.add(run)
    await db.flush()  # need run.id for the items below

    for position, prospect in enumerate(targets):
        db.add(
            BatchRunItem(
                run_id=run.id, prospect_id=prospect.id, position=position, status="queued"
            )
        )
    await db.commit()

    await advance_run(db, run.id)

    refreshed = await get_run(db, tenant_id, run.id)
    assert refreshed is not None  # just created it, in this same tenant
    return refreshed


async def get_run(db: AsyncSession, tenant_id: uuid.UUID, run_id: uuid.UUID) -> BatchRun | None:
    result = await db.execute(
        select(BatchRun)
        .where(BatchRun.id == run_id, BatchRun.tenant_id == tenant_id)
        .options(selectinload(BatchRun.items))
    )
    return result.scalar_one_or_none()


async def prospect_names_for_run(db: AsyncSession, run: BatchRun) -> dict[uuid.UUID, str]:
    """Prospect.name for every item in `run`, keyed by prospect_id — BatchRunItem only
    stores the id, and the run-progress view (api/prospects.py) needs a name to render
    anything readable.
    """
    prospect_ids = [item.prospect_id for item in run.items]
    if not prospect_ids:
        return {}
    result = await db.execute(
        select(Prospect.id, Prospect.name).where(Prospect.id.in_(prospect_ids))
    )
    return dict(result.tuples().all())


async def _get_run_unscoped(db: AsyncSession, run_id: uuid.UUID) -> BatchRun | None:
    """Unscoped counterpart of get_run, for the worker task (advance_run runs off a
    call_id / run_id the fanout hook already resolved, not an HTTP caller — same
    reasoning as prospect_service.get_prospect_unscoped).
    """
    result = await db.execute(select(BatchRun).where(BatchRun.id == run_id))
    return result.scalar_one_or_none()


async def cancel_run(db: AsyncSession, tenant_id: uuid.UUID, run_id: uuid.UUID) -> BatchRun | None:
    """Stop dialing further items. The item currently `dialing` (if any) is left alone —
    that call is already live and will run to its natural end; it just won't trigger a
    next dial, because advance_run() bails out as soon as it sees status != "running".
    """
    run = await get_run(db, tenant_id, run_id)
    if not run:
        return None
    if run.status == "running":
        run.status = "cancelled"
        run.finished_at = datetime.now(UTC)
        await db.commit()
    return run


async def claim_next(db: AsyncSession, run_id: uuid.UUID) -> BatchRunItem | None:
    """Atomically claim the next queued item in dial order, or None if there is nothing
    left to claim — either the run is exhausted, or another concurrent advance_run()
    call already took it. See module docstring for why this is safe without explicit
    row locking.
    """
    next_id = (
        await db.execute(
            select(BatchRunItem.id)
            .where(BatchRunItem.run_id == run_id, BatchRunItem.status == "queued")
            .order_by(BatchRunItem.position)
            .limit(1)
        )
    ).scalar_one_or_none()
    if next_id is None:
        return None

    claimed_id = (
        await db.execute(
            update(BatchRunItem)
            .where(BatchRunItem.id == next_id, BatchRunItem.status == "queued")
            .values(status="dialing", dialed_at=datetime.now(UTC))
            .returning(BatchRunItem.id)
        )
    ).scalar_one_or_none()
    await db.commit()
    if claimed_id is None:
        return None  # lost the race to another advance() for this run

    return (
        await db.execute(select(BatchRunItem).where(BatchRunItem.id == claimed_id))
    ).scalar_one()


async def _variables_for(
    external_agent_id: str, run: BatchRun, prospect: Prospect
) -> dict[str, str]:
    """The {{placeholders}} for one dial: the run's operator-typed values, with this
    prospect's own details layered on top.

    Per-prospect values win over run-level ones, which is the opposite of the usual
    "explicit beats inferred" rule and is the entire point of this function. A batch
    dials many companies from one form; a `company_name` typed once would introduce
    itself as the same business to all of them. `suggest_for_prospect` omits blanks
    rather than returning "", so a prospect with no city still falls back to whatever
    the operator supplied instead of blanking it.

    Fetching the declared list here costs one extra platform call per dial (place_...
    fetches it again to validate). That's noise next to placing a phone call, and it
    keeps place_platform_agent_call's contract — shared with the single-call path —
    untouched.
    """
    declared = await test_call_service.get_platform_agent_variables(external_agent_id)
    if not declared:
        return dict(run.dynamic_variables or {})
    return {
        **(run.dynamic_variables or {}),
        **prospect_variables.suggest_for_prospect(declared, prospect),
    }


async def _dial_item(
    db: AsyncSession, run: BatchRun, item: BatchRunItem, prospect: Prospect
) -> bool:
    """Place the call for one already-claimed item, or mark it skipped. Mirrors the
    per-prospect branch of POST /prospects/batch-call (api/prospects.py) — same
    eligibility rules, just one item instead of a loop. Returns True iff a call was
    actually placed (the run should now wait for that call's terminal webhook);
    False means the item was skipped and the caller should claim the next one.
    """
    # batch_call_targets filters Prospect.phone.isnot(None); narrow for the type checker
    # (same assert as the /batch-call endpoint this mirrors).
    assert prospect.phone is not None

    external_agent_id = run.external_agent_id
    agent_id = run.agent_id
    try:
        if external_agent_id:
            call = await test_call_service.place_platform_agent_call(
                db,
                run.tenant_id,
                external_agent_id,
                prospect.phone,
                dynamic_variables=await _variables_for(external_agent_id, run, prospect),
                prospect_id=prospect.id,
            )
        else:
            assert agent_id is not None  # enforced at start_run time
            agent = await agent_service.get_agent(db, agent_id, run.tenant_id)
            if not agent:
                item.status, item.skip_reason = "skipped", "agent not found"
                await db.commit()
                return False
            if prospect.research_status != "ready":
                item.status = "skipped"
                item.skip_reason = f"research is '{prospect.research_status}', not ready"
                await db.commit()
                return False
            personalized_prompt = _build_personalized_prompt(agent, prospect)
            call = await test_call_service.place_test_call(
                db,
                agent.id,
                run.tenant_id,
                prospect.phone,
                system_prompt_override=personalized_prompt,
                prospect_id=prospect.id,
            )
    except test_call_service.TestCallError as exc:
        item.status, item.skip_reason = "skipped", str(exc)
        await db.commit()
        return False

    local_call = await call_service.get_call_by_external_id(db, call["call_id"])
    item.call_id = local_call.id if local_call else None
    await prospect_service.record_call(db, prospect.id, run.tenant_id)
    await db.commit()
    return True


async def advance_run(db: AsyncSession, run_id: uuid.UUID) -> None:
    """Claim and dial the run's next queued item. Loops past items that turn out
    ineligible (research not ready, agent gone, TestCallError) rather than stalling —
    a skip produces no call, so nothing would ever trigger the next advance() if we
    stopped and waited on it. Called both right after start_run() (to fire item #1)
    and from mark_item_done_and_advance() (to fire everything after it).
    """
    run = await _get_run_unscoped(db, run_id)
    if not run or run.status != "running":
        return

    while True:
        item = await claim_next(db, run_id)
        if item is None:
            await _finish_if_exhausted(db, run)
            return

        prospect = await prospect_service.get_prospect_unscoped(db, item.prospect_id)
        if not prospect:
            item.status, item.skip_reason = "skipped", "prospect not found"
            await db.commit()
            continue

        if await _dial_item(db, run, item, prospect):
            return  # a call is now live; wait for its terminal webhook


async def _finish_if_exhausted(db: AsyncSession, run: BatchRun) -> None:
    remaining = (
        await db.execute(
            select(BatchRunItem.id).where(
                BatchRunItem.run_id == run.id, BatchRunItem.status.in_(("queued", "dialing"))
            )
        )
    ).first()
    if remaining is None:
        run.status = "done"
        run.finished_at = datetime.now(UTC)
        await db.commit()


async def mark_item_done_and_advance(db: AsyncSession, call: Call) -> uuid.UUID | None:
    """Called from call_service._fanout_post_call for every terminal call. Flips this
    call's batch item to "done" and returns its run_id for the caller to enqueue
    advance_batch_run() on — or None if this call isn't part of any active batch item
    (not a batch call at all, or its item was already marked done by an earlier fanout
    for the same call, per _fanout_post_call's "runs more than once" contract).

    Deliberately does not call advance_run() itself: this runs inline on the webhook
    request path (<200ms budget, ADR-005), and dialing the next call is an outbound
    HTTP request — the caller must hand it to Celery, not run it here.
    """
    run_id = (
        await db.execute(
            update(BatchRunItem)
            .where(BatchRunItem.call_id == call.id, BatchRunItem.status == "dialing")
            .values(status="done")
            .returning(BatchRunItem.run_id)
        )
    ).scalar_one_or_none()
    if run_id is None:
        # 0 rows matched — not a batch call, or already marked done by an earlier
        # fanout for this call. Nothing was written, so there's nothing to commit or
        # undo; rolling back here would discard whatever else this request/test's
        # session has pending, which isn't ours to touch.
        return None

    await db.commit()
    return run_id


async def mark_item_stalled_and_advance(db: AsyncSession, item_id: uuid.UUID) -> uuid.UUID | None:
    """Called by batch_tasks.sweep_stalled_batches for an item claimed as "dialing"
    that never got a local call_id at all (place_test_call/place_platform_agent_call
    raised something other than TestCallError, or the worker died mid-dial) — there is
    no call to reconcile, so the only option is to give up on this item and move on.
    Guarded the same way as mark_item_done_and_advance so a webhook that arrives in the
    same instant this sweep runs can't be undone by it.
    """
    run_id = (
        await db.execute(
            update(BatchRunItem)
            .where(BatchRunItem.id == item_id, BatchRunItem.status == "dialing")
            .values(status="skipped", skip_reason="stalled: no call record")
            .returning(BatchRunItem.run_id)
        )
    ).scalar_one_or_none()
    if run_id is None:
        return None  # already advanced past by a concurrent webhook — see sibling note above

    await db.commit()
    return run_id
