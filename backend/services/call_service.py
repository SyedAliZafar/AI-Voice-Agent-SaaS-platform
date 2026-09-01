"""Call lifecycle: creation at outbound-placement time, and webhook-driven updates.

Design note (the reason this file previously had the wrong content — see phase2.md/
git history): webhook payloads (schemas/webhook.py) carry only the voice platform's own
call_id, never our agent_id/tenant_id. We can't create a Call row from a webhook alone.

This project only originates OUTBOUND calls today (test_call_service.place_test_call,
used directly and via the prospects /call endpoint) — and outbound call placement
already receives the platform's call_id back from create_outbound_call(). So the Call
row is created THERE (create_outbound_call_record, called by test_call_service), with
external_id set to that call_id. Webhook handlers below just look up by external_id and
update; if no match is found (an inbound call — not wired to a real phone number/agent
in this project yet), they log and no-op rather than crash. ADR-005: webhook handlers
must stay fast and must never 500 on events they can't fully resolve.

Two paths write terminal call state, and they deliberately converge on ONE writer
(apply_retell_call_state):

1. Webhooks — fast, push-based, but only as reliable as the tunnel. A missed call_ended
   (tunnel down, PUBLIC_BASE_URL unset, webhook_url never registered) used to strand a
   row at in_progress permanently.
2. Reconciliation — reconcile_call() pulls authoritative state from Retell's
   GET /v2/get-call. This is the self-healing path, exposed as POST /api/calls/sync.

Keeping both on one writer is the point: if they drifted, a reconciled call and a
webhook-updated call could disagree about the same call's outcome.
"""

import logging
import uuid
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.call import Call, CallEvent, Transcript
from backend.models.prospect import Prospect

logger = logging.getLogger(__name__)

# Retell disconnection_reason -> our Call.status. Anything ended and not listed here is
# a normal completion ("resolved"). Source: Retell's call object docs — this is their
# full documented enum, not a guessed subset. error_* reasons are handled separately by
# the reason.startswith("error") branch in _status_for, so they're deliberately absent
# here rather than duplicated.
_TRANSFER_REASONS = {"call_transfer"}
_FAILURE_REASONS = {
    "dial_busy",
    "dial_failed",
    "dial_no_answer",
    "voicemail_reached",
    "machine_detected",
    "registered_call_timeout",
    "no_valid_payment",
    "concurrency_limit_reached",
    "no_concurrency_fallback",
    "scam_detected",
    "error_user_not_joined",
    # The callee declined or let it ring out unanswered — never became a real
    # conversation, same bucket as dial_no_answer above.
    "user_declined",
    "invalid_destination",
    "telephony_provider_permission_denied",
    "telephony_provider_unavailable",
    "sip_routing_error",
    "marked_as_spam",
}

# Retell's call_analysis.user_sentiment is categorical; Call.sentiment_score is a float.
_SENTIMENT_SCORES = {"positive": 1.0, "neutral": 0.5, "negative": 0.0}


async def list_calls(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    agent_id: uuid.UUID | None,
    status: str | None,
    limit: int = 50,
    offset: int = 0,
) -> list[Call]:
    query = select(Call).where(Call.tenant_id == tenant_id)
    if agent_id:
        query = query.where(Call.agent_id == agent_id)
    if status:
        query = query.where(Call.status == status)
    query = query.order_by(Call.started_at.desc()).limit(limit).offset(offset)

    result = await db.execute(query)
    return list(result.scalars().all())


async def get_call(db: AsyncSession, call_id: uuid.UUID, tenant_id: uuid.UUID) -> Call | None:
    """Fetch one call, scoped to its tenant (ADR-001). Another tenant's call reads as
    None so callers 404 rather than 403, keeping ids non-enumerable.
    """
    result = await db.execute(select(Call).where(Call.id == call_id, Call.tenant_id == tenant_id))
    return result.scalar_one_or_none()


async def get_transcript(
    db: AsyncSession, call_id: uuid.UUID, tenant_id: uuid.UUID
) -> Transcript | None:
    """Fetch a call's transcript, scoped via the parent call's tenant.

    Transcript has no tenant_id of its own, so isolation is enforced by joining to Call —
    a transcript is only reachable through a call the tenant owns.
    """
    result = await db.execute(
        select(Transcript)
        .join(Call, Transcript.call_id == Call.id)
        .where(Transcript.call_id == call_id, Call.tenant_id == tenant_id)
    )
    return result.scalar_one_or_none()


async def list_call_events(
    db: AsyncSession, call_id: uuid.UUID, tenant_id: uuid.UUID, limit: int = 200
) -> list[CallEvent]:
    """A call's CallEvent trail, oldest first, scoped via the parent call's tenant.

    Same isolation mechanism as get_transcript above: CallEvent has no tenant_id of its
    own, so the join to Call is what makes another tenant's trail unreachable.

    Oldest-first because this is read as a timeline of what the agent did while the call
    ran — newest-first would mean reading a conversation backwards. Ordered by (ts, id)
    rather than ts alone because record_llm_events writes a whole turn's samples with one
    shared `now`: ties are arbitrary either way, but including id makes them *stable*, so
    the same call doesn't reshuffle its own timeline between two page loads.

    Capped rather than paginated: even a long call with tool calls on every turn is a few
    hundred rows, and an operator reading a trail wants the whole call, not page 3 of it.
    """
    result = await db.execute(
        select(CallEvent)
        .join(Call, CallEvent.call_id == Call.id)
        .where(CallEvent.call_id == call_id, Call.tenant_id == tenant_id)
        .order_by(CallEvent.ts.asc(), CallEvent.id.asc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def get_call_by_external_id(db: AsyncSession, external_call_id: str) -> Call | None:
    """Tenant-unscoped by necessity — used both by webhook handlers (no tenant context
    yet) and backend/api/retell_ws.py (Retell's frames carry only its own call_id, no
    auth). This is the resolution step that TURNS a bare call_id into a tenant/agent.
    """
    result = await db.execute(select(Call).where(Call.external_id == external_call_id))
    return result.scalar_one_or_none()


async def create_outbound_call_record(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    agent_id: uuid.UUID | None,
    external_id: str,
    caller_number: str,
    lead_id: uuid.UUID | None = None,
    prospect_id: uuid.UUID | None = None,
    system_prompt_override: str | None = None,
    external_agent_id: str | None = None,
) -> Call:
    """Called by test_call_service right after the voice platform confirms an
    outbound call was placed — see module docstring for why creation happens here
    rather than on the call_started webhook.

    `system_prompt_override` is only meaningful for use_custom_llm agents: it's how a
    personalized, call-scoped prompt reaches backend/api/retell_ws.py, which resolves it
    off this row rather than from Agent.system_prompt. See Call.system_prompt_override.

    `lead_id` / `prospect_id` tag the row so _fanout_post_call can hand a terminal call to
    lead_service.evaluate_call_outcome (ADR-011) or prospect_service.classify_call_outcome
    respectively. At most one is ever set; both are None for a plain test or web call.

    `agent_id` and `external_agent_id` are the two ways a call names its agent, and
    exactly one must be given: a local Agent row we provisioned, or a platform-native
    agent built in the platform's own dashboard (ADR-012). Enforced here rather than left
    to the database, because a row with neither is unattributable and a row with both
    would make "which agent ran this call" ambiguous for every reader downstream.
    """
    if (agent_id is None) == (external_agent_id is None):
        raise ValueError("exactly one of agent_id / external_agent_id must be set")

    call = Call(
        tenant_id=tenant_id,
        agent_id=agent_id,
        external_agent_id=external_agent_id,
        caller_number=caller_number,
        status="in_progress",
        started_at=datetime.now(UTC),
        external_id=external_id,
        lead_id=lead_id,
        prospect_id=prospect_id,
        system_prompt_override=system_prompt_override,
    )
    db.add(call)
    await db.commit()
    await db.refresh(call)
    return call


async def handle_call_started(external_call_id: str, platform: str) -> None:
    """No-op by design for calls we originated (the Call row already exists with
    status=in_progress from create_outbound_call_record). Logs and returns for
    anything else, since we can't attribute an unknown call to a tenant/agent yet.
    """
    logger.info(
        "call_started webhook received",
        extra={"external_call_id": external_call_id, "platform": platform},
    )


async def _get_or_create_transcript(db: AsyncSession, call: Call) -> Transcript:
    """Fetch a call's Transcript row, creating an empty one if none exists yet.
    Shared by both transcript writers (_write_transcript, record_turns) so there's
    one upsert, not two. Caller commits/flushes as needed.
    """
    existing = await get_transcript(db, call.id, call.tenant_id)
    if existing:
        return existing
    transcript = Transcript(call_id=call.id, full_text="", turns=[])
    db.add(transcript)
    return transcript


async def _write_transcript(
    db: AsyncSession, call: Call, transcript_text: str, *, transcript: Transcript | None = None
) -> None:
    """Upsert a call's transcript full_text — Retell's own raw transcript string
    (payload["transcript"]), kept separate from the structured turns record_turns
    writes. Caller commits.

    `transcript` lets a caller that has already loaded this call's row hand it in rather
    than paying for the same SELECT again — see apply_retell_call_state, which needs the
    row up to three times per call and now fetches it once. Omitted, behaviour is
    unchanged.
    """
    row = transcript if transcript is not None else await _get_or_create_transcript(db, call)
    row.full_text = transcript_text


# Retell's transcript role -> our storage role, matching what TranscriptViewer.tsx and
# frontend/src/lib/types.ts's TranscriptTurn already expect ("caller" | "agent"). Kept
# separate from retell_ws.py's _ROLE_MAP, which maps onto OpenAI's "user"/"assistant"
# for LLM conversation history — a different vocabulary for a different consumer.
_RETELL_STORAGE_ROLE_MAP = {"user": "caller", "agent": "agent"}


def parse_retell_turns(transcript_items: list[dict[str, Any]]) -> list[dict]:
    """Retell uses the same [{role, content, ...}, ...] shape in two places: the live
    WS handler's response_required/reminder_required frames (backend/api/retell_ws.py)
    and the post-call transcript_object on call_ended/call_analyzed payloads. Both
    convert here into the {role, text} shape record_turns expects.
    """
    turns = []
    for item in transcript_items:
        content = item.get("content")
        if not isinstance(content, str):
            continue
        role = _RETELL_STORAGE_ROLE_MAP.get(item.get("role", ""), "caller")
        turns.append({"role": role, "text": content})
    return turns


async def record_turns(
    db: AsyncSession,
    call: Call,
    turns: list[dict],
    *,
    sync_full_text: bool = True,
    transcript: Transcript | None = None,
) -> None:
    """Wholesale-replace a call's Transcript.turns.

    Retell always sends the FULL transcript so far — both on every live WS
    response_required frame and in transcript_object on the post-call payload — never
    a delta. So each call here is an idempotent replace: a dropped write self-corrects
    on the next turn, and there's no accumulator state to keep anywhere.

    Preserves `ts` for turns unchanged at the same index, so re-recording an unchanged
    prefix doesn't restamp already-spoken lines to "now"; new or changed turns get
    now(UTC). sync_full_text=False (used by apply_retell_call_state) leaves full_text
    to _write_transcript's separate write of Retell's own raw transcript string —
    turns is the only thing this function owns there. The live WS handler has no raw
    string to fall back on, so it takes the default and gets full_text synthesized
    from turns.

    `transcript` is the same already-loaded-row optimization _write_transcript takes;
    omitted, this fetches its own as before.

    Caller commits.
    """
    row = transcript if transcript is not None else await _get_or_create_transcript(db, call)
    existing = row.turns or []
    now = datetime.now(UTC).isoformat()

    new_turns = []
    for i, turn in enumerate(turns):
        role = turn["role"]
        text = turn.get("text", "")
        unchanged = (
            i < len(existing)
            and existing[i].get("role") == role
            and existing[i].get("text") == text
        )
        ts = existing[i].get("ts") if unchanged else None
        ts = ts or now
        new_turns.append({"role": role, "text": text, "ts": ts})

    row.turns = new_turns
    if sync_full_text:
        row.full_text = "\n".join(f"{t['role']}: {t['text']}" for t in new_turns)


async def record_llm_events(db: AsyncSession, call: Call, llm_events: list[dict]) -> None:
    """One CallEvent(event_type="llm_timing") row per llm_service.get_agent_response()
    completions.create() call for this turn (see llm_service's llm_events param) — the
    before/after baseline requested ahead of the streaming-architecture work.

    Caller commits. No-op on an empty list so a text-only turn (no tool calls, or
    llm_events never populated) doesn't write empty rows.
    """
    if not llm_events:
        return
    now = datetime.now(UTC)
    for event in llm_events:
        db.add(CallEvent(call_id=call.id, event_type="llm_timing", payload=event, ts=now))


async def record_call_event(db: AsyncSession, call: Call, event_type: str, payload: dict) -> None:
    """One CallEvent of an arbitrary type — the general form of the typed writers above.

    Exists for events that are neither tool calls nor LLM timings, the first being
    "ivr_hangup" (retell_ws ended a call because the far end was a phone menu). Without a
    row, an auto-hangup is invisible: the call just shows a short duration and nobody can
    tell a menu from a prospect who hung up, which is exactly the thing you need to audit
    when tuning the detector. Caller commits.
    """
    db.add(CallEvent(call_id=call.id, event_type=event_type, payload=payload, ts=datetime.now(UTC)))


async def record_tool_event(db: AsyncSession, call: Call, event: dict) -> None:
    """One CallEvent(event_type="tool_call") row per llm_service._execute_tool_calls
    on_tool_event callback — a "dispatched" row written before the tool's handler runs
    and a "result"/"error" row after (see event["phase"]). This is the durable trace that
    survives a barge-in cancelling the surrounding generation task (ADR-009): the
    "dispatched" row proves a side-effecting call (e.g. book_appointment's Cal.com POST)
    was made even if the turn that made it never reaches _persist_and_publish_turn.

    Caller commits. retell_ws.py calls this from a tracked, fire-and-forget task (never
    inline) — a DB round-trip in front of the tool call itself would put Postgres latency
    on the turn path, the same reason _persist_and_publish_turn runs after the response
    frame is sent. Swallows nothing itself; the caller's task wrapper is responsible for
    catching and logging so a Postgres hiccup can't take down a live call.
    """
    db.add(CallEvent(call_id=call.id, event_type="tool_call", payload=event, ts=datetime.now(UTC)))
    await db.commit()


async def handle_transcript_update(
    db: AsyncSession, external_call_id: str, transcript_text: str
) -> None:
    """Standalone transcript write, kept for the Vapi path and direct callers.

    Note: Retell has no transcript_update webhook — its transcripts ride along on the
    call_ended/call_analyzed payloads and go through apply_retell_call_state instead.
    """
    call = await get_call_by_external_id(db, external_call_id)
    if not call:
        logger.info(
            "transcript_update for unknown call, ignoring",
            extra={"external_call_id": external_call_id},
        )
        return

    await _write_transcript(db, call, transcript_text)
    await db.commit()


def _status_for(call_status: str, disconnection_reason: str | None) -> str | None:
    """Map Retell's call_status/disconnection_reason onto our Call.status.

    Returns None when Retell says the call hasn't reached a terminal state yet, so
    callers leave the existing status alone rather than writing a wrong one.
    """
    if call_status == "error":
        return "failed"
    if call_status != "ended":
        # registered | not_connected | ongoing — still live, nothing to conclude.
        return None

    reason = (disconnection_reason or "").lower()
    if reason in _TRANSFER_REASONS:
        return "escalated"
    if reason in _FAILURE_REASONS or reason.startswith("error"):
        return "failed"
    return "resolved"


async def apply_retell_call_state(db: AsyncSession, call: Call, payload: dict[str, Any]) -> bool:
    """Single writer for terminal call state, shared by the webhook and reconcile paths.

    `payload` is Retell's call object — the nested "call" from a webhook, or the body of
    GET /v2/get-call. Both carry the same fields, which is what lets one function serve
    both. Returns True if anything changed. Caller commits.

    Prefers Retell's own duration_ms over wall-clock arithmetic: a reconcile can run days
    after the call ended, so computing `now - started_at` there would be wildly wrong.
    """
    changed = False

    raw_reason = payload.get("disconnection_reason")
    new_status = _status_for(str(payload.get("call_status") or ""), raw_reason)
    if new_status and call.status != new_status:
        call.status = new_status
        changed = True

    # Keep Retell's raw reason verbatim — _status_for collapses voicemail/declined/
    # rang-out all into "failed", and prospect outcome classification needs them apart.
    if isinstance(raw_reason, str) and raw_reason and call.disconnection_reason != raw_reason:
        call.disconnection_reason = raw_reason
        changed = True

    duration_ms = payload.get("duration_ms")
    if isinstance(duration_ms, int | float) and duration_ms > 0:
        duration_sec = int(duration_ms / 1000)
        if call.duration_sec != duration_sec:
            call.duration_sec = duration_sec
            changed = True
    elif new_status and not call.duration_sec:
        # Terminal but no duration reported (older payloads) — fall back to wall clock.
        started_at = (
            call.started_at if call.started_at.tzinfo else call.started_at.replace(tzinfo=UTC)
        )
        call.duration_sec = max(0, int((datetime.now(UTC) - started_at).total_seconds()))
        changed = True

    sentiment = (payload.get("call_analysis") or {}).get("user_sentiment")
    if isinstance(sentiment, str):
        score = _SENTIMENT_SCORES.get(sentiment.lower())  # "Unknown" -> None, left unset
        if score is not None and call.sentiment_score != score:
            call.sentiment_score = score
            changed = True

    # This call's Transcript row, loaded at most once and reused by all three consumers
    # below. Each used to fetch it independently — _write_transcript, record_turns and the
    # answered_by_human check — costing three identical SELECTs per call. Invisible at one
    # call per webhook; the dominant cost in backfill_from_platform, which runs this in a
    # loop over the platform's entire call history against a remote database.
    #
    # Deliberately created only when there is something to WRITE. The answered_by_human
    # branch falls back to a read-only get_transcript so a terminal call that never had a
    # transcript doesn't get an empty row inserted for it, which is what get-or-create
    # here would silently start doing.
    transcript: Transcript | None = None

    transcript_text = payload.get("transcript")
    if isinstance(transcript_text, str) and transcript_text.strip():
        transcript = await _get_or_create_transcript(db, call)
        await _write_transcript(db, call, transcript_text, transcript=transcript)
        changed = True

    # transcript_object is Retell's structured per-turn record. Parsing it here makes
    # this the authoritative final write for Transcript.turns — including for the
    # hosted-LLM path, which has no live WS handler to have written turns already.
    transcript_object = payload.get("transcript_object")
    if isinstance(transcript_object, list) and transcript_object:
        turns = parse_retell_turns(transcript_object)
        if turns:
            if transcript is None:
                transcript = await _get_or_create_transcript(db, call)
            # sync_full_text=False: transcript_text above (Retell's own raw string) is
            # the better full_text when both are present; don't clobber it with a
            # synthesized "role: text" join.
            await record_turns(db, call, turns, sync_full_text=False, transcript=transcript)
            changed = True

    # Whether a person actually spoke — computed once the call is terminal, off the
    # transcript this function has just finished writing. `caller` turns come only from
    # the far end, so a voicemail pickup or an instant hangup lands zero. Mirrors the
    # "human answered and talked" test in lead_service.evaluate_call_outcome.
    effective_status = new_status or call.status
    if effective_status in ("resolved", "escalated", "failed"):
        # Reuses the row written above when there was one; only pays for a SELECT when
        # this payload carried no transcript at all (see the note where `transcript` is
        # declared for why this stays a read rather than a get-or-create).
        existing = (
            transcript
            if transcript is not None
            else await get_transcript(db, call.id, call.tenant_id)
        )
        answered = any(t.get("role") == "caller" for t in (existing.turns if existing else []))
        if call.answered_by_human != answered:
            call.answered_by_human = answered
            changed = True

    return changed


async def _fanout_post_call(
    db: AsyncSession, call: Call, *, prospect: Prospect | None = None
) -> None:
    """Everything that must happen once a call reaches a terminal status.

    Was `_maybe_advance_lead`, then `_fanout_lead_post_call` — renamed again once
    prospect outcome classification joined the lead scheduler here, since the seam is
    no longer lead-specific.

    **All three callers must keep going through this one function.** `handle_call_ended`,
    `handle_call_analyzed` and `reconcile_call` each reach terminal state by a different
    route, and routing them all through here is what ADR-007's single-writer rule buys:
    anything hung off this point inherits reconciliation's self-healing for free, so a
    webhook that never arrives doesn't need its own recovery path. That's how the lead
    scheduler got resilient (ADR-011), and it's why prospect classification belongs here
    rather than in the webhook handler.

    Two rules for whatever gets added below:
    - **Enqueue, never execute — unless the work is a couple of local queries.** This
      runs on the webhook request path (<200ms budget, ADR-005); anything heavier than a
      few statements goes to Celery. `evaluate_call_outcome` / `classify_call_outcome`
      are cheap enough to stay inline, and their state must be correct before anything
      downstream reads it.
    - **Assume it runs more than once per call.** call_ended and call_analyzed both reach
      a terminal status, and a later reconcile can too. Each consumer carries its own
      idempotency guard (`evaluate_call_outcome`'s `in_flight` check;
      `classify_call_outcome`'s forward-only status ordering).

    Imported locally, not at module level: those services don't import call_service
    today, and keeping the dependency one-directional and lazy avoids ever having to
    care about import order.
    """
    if call.status not in ("resolved", "escalated", "failed"):
        return

    if call.lead_id:
        # Scheduler bookkeeping — succeeded, or back on the backoff ladder (ADR-011).
        from backend.services import lead_service

        await lead_service.evaluate_call_outcome(db, call)

    if call.prospect_id:
        # Campaign-outcome axis — advance Prospect.status off how this call ended.
        # `prospect`, when supplied, is an already-loaded row (backfill_from_platform
        # preloads them all); the webhook and reconcile paths pass nothing and this
        # fetches its own, unchanged.
        from backend.services import prospect_service

        await prospect_service.classify_call_outcome(db, call, prospect=prospect)


async def handle_call_ended(
    db: AsyncSession, external_call_id: str, payload: dict[str, Any] | None = None
) -> None:
    call = await get_call_by_external_id(db, external_call_id)
    if not call:
        logger.info(
            "call_ended for unknown call, ignoring",
            extra={"external_call_id": external_call_id},
        )
        return

    # A call_ended webhook is itself proof the call is over, even if the payload omits
    # call_status — default it so _status_for reaches a terminal verdict.
    data = dict(payload or {})
    data.setdefault("call_status", "ended")

    await apply_retell_call_state(db, call, data)
    await db.commit()
    await _fanout_post_call(db, call)


async def handle_call_analyzed(
    db: AsyncSession, external_call_id: str, payload: dict[str, Any]
) -> None:
    """Retell's post-call analysis — this is where user_sentiment arrives, and where the
    final transcript is most complete. Fired after call_ended.
    """
    call = await get_call_by_external_id(db, external_call_id)
    if not call:
        logger.info(
            "call_analyzed for unknown call, ignoring",
            extra={"external_call_id": external_call_id},
        )
        return

    await apply_retell_call_state(db, call, payload)
    await db.commit()
    await _fanout_post_call(db, call)


async def reconcile_call(db: AsyncSession, call: Call, adapter: Any) -> bool:
    """Pull authoritative state for one call from Retell and apply it.

    The self-healing counterpart to the webhook path: if a call_ended was never delivered
    (no tunnel, unregistered webhook_url, tunnel restarted mid-call), this is what
    unsticks the row. Returns True if the call changed.
    """
    if not call.external_id:
        return False

    try:
        payload = await adapter.get_call(call.external_id)
    except Exception:
        logger.warning(
            "reconcile: failed to fetch call from platform",
            extra={"external_call_id": call.external_id},
            exc_info=True,
        )
        return False

    changed = await apply_retell_call_state(db, call, payload)
    if changed:
        await db.commit()
        await _fanout_post_call(db, call)
    return changed


async def end_call(db: AsyncSession, call: Call, adapter: Any) -> bool:
    """Hang up a live call now, then record how it ended. Returns True if the row changed.

    The emergency stop. Deliberately two steps in this order: the hangup is what the
    operator actually needs and must not be delayed or skipped by bookkeeping, so it goes
    first and is allowed to raise; the follow-up reconcile is best-effort tidying.

    Terminal state is written by reconciling against Retell rather than set here, because
    ADR-007 makes apply_retell_call_state the single writer for it — inventing a second
    one would mean this path could disagree with the webhook about how the call ended,
    and Retell (which knows the real disconnection_reason and duration) is the authority.
    If the reconcile fails or races Retell finalizing the call, the row stays in_progress
    and the ordinary call_ended webhook — or POST /api/calls/sync — closes it out. The
    call is still hung up either way, which is the part that mattered.
    """
    if not call.external_id:
        raise ValueError("Call has no external_id — nothing to hang up on the platform")

    await adapter.stop_call(call.external_id)
    logger.info(
        "call stopped by operator",
        extra={"call_id": str(call.id), "external_call_id": call.external_id},
    )
    return await reconcile_call(db, call, adapter)


async def reconcile_stale_calls(db: AsyncSession, tenant_id: uuid.UUID, adapter: Any) -> int:
    """Reconcile every still-in_progress call for a tenant. Returns how many changed."""
    result = await db.execute(
        select(Call).where(
            Call.tenant_id == tenant_id,
            Call.status == "in_progress",
            Call.external_id.is_not(None),
        )
    )
    calls = list(result.scalars().all())

    updated = 0
    for call in calls:
        if await reconcile_call(db, call, adapter):
            updated += 1
    return updated


# platform history import ------------------------------------------------------------


def counterparty_number(payload: dict[str, Any]) -> str | None:
    """The number at the *other end* of a call — the prospect's, whichever way it was
    dialed. None for web calls, which have no phone number at all.

    Call.caller_number has always held this for outbound calls, so keeping inbound on the
    same convention is what lets one column be the phone-match key in both directions.
    """
    if payload.get("call_type") == "web_call":
        return None
    number = (
        payload.get("from_number")
        if payload.get("direction") == "inbound"
        else payload.get("to_number")
    )
    return number if isinstance(number, str) and number else None


async def backfill_from_platform(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    adapter: Any,
    *,
    since_ms: int | None = None,
    max_calls: int = 1000,
) -> dict[str, int]:
    """Import the platform's own call history into `calls`, linking each to a prospect
    by phone number. Returns counts for the operator.

    This is the third path into terminal call state, alongside webhooks and per-call
    reconciliation — and the only one that can see a call this backend never placed. A
    batch run started from Retell's dashboard (ADR-012) creates no local Call row and
    fires its webhooks at whatever tunnel URL happened to be registered that day, so
    without this the entire outreach ledger silently disagrees with reality: prospects
    sit at "not_called" having been dialed five times.

    Idempotent, and safe to re-run as often as you like:
      - Rows are keyed on `external_id`, so a call already imported is updated, not
        duplicated.
      - Terminal state goes through apply_retell_call_state + _fanout_post_call like
        every other path, so classify_call_outcome's forward-only status ladder applies.
      - call_count is *recomputed* from the imported rows rather than incremented, since
        record_call() never ran for dashboard-placed calls and incrementing on each
        re-run would inflate it without bound.

    Calls that match no prospect (inbound to our own number, web calls, one-off test
    dials) are still stored, with prospect_id left null — the local call history should
    be complete even where the prospect ledger has nothing to say.
    """
    from backend.services.prospect_service import phone_match_key

    history = await adapter.list_call_history(since_ms=since_ms, max_calls=max_calls)

    # Prospect phones come from Google Places / scraped lists with their own spacing and,
    # for UK numbers, often national format ("020 7733 5265"); the platform reports strict
    # E.164 ("+442077335265"). phone_match_key reduces both to the same trailing digits —
    # comparing raw or merely-stripped strings finds nothing.
    prospect_rows = await db.execute(
        select(Prospect.id, Prospect.phone).where(
            Prospect.tenant_id == tenant_id, Prospect.phone.is_not(None)
        )
    )
    by_phone: dict[str, uuid.UUID] = {}
    for prospect_id, phone in prospect_rows.all():
        key = phone_match_key(phone)
        # First writer wins: two prospect rows sharing a number is a data problem to fix
        # in the list, not something to resolve arbitrarily on every sync.
        if key and key not in by_phone:
            by_phone[key] = prospect_id

    stats = dict.fromkeys(("fetched", "created", "updated", "matched", "unmatched"), 0)
    stats["fetched"] = len(history)
    touched_prospects: set[uuid.UUID] = set()

    # Two prefetches, both for the same reason: this loop runs once per call in the
    # platform's entire history, and every query inside it is a separate round trip to a
    # remote database. Doing them per-call made a routine 30-day sync take upwards of ten
    # minutes — long enough that the operator reasonably reads it as hung.
    #
    # Neither changes what the loop does, only how many times it asks. Matching the
    # existing lookups exactly: calls are keyed on external_id with no tenant filter (as
    # get_call_by_external_id is, deliberately — see its docstring), prospects are loaded
    # unscoped by id (as get_prospect_unscoped is).
    external_ids = [
        payload["call_id"]
        for payload in history
        if isinstance(payload.get("call_id"), str) and payload["call_id"]
    ]
    calls_by_external_id: dict[str, Call] = {}
    if external_ids:
        existing_calls = await db.execute(select(Call).where(Call.external_id.in_(external_ids)))
        calls_by_external_id = {
            call.external_id: call for call in existing_calls.scalars() if call.external_id
        }

    prospects_by_id: dict[Any, Prospect] = {}
    if by_phone:
        matched_prospects = await db.execute(
            select(Prospect).where(Prospect.id.in_(set(by_phone.values())))
        )
        prospects_by_id = {prospect.id: prospect for prospect in matched_prospects.scalars()}

    for payload in history:
        external_id = payload.get("call_id")
        if not isinstance(external_id, str) or not external_id:
            continue

        number = counterparty_number(payload)
        key = phone_match_key(number)
        prospect_id = by_phone.get(key) if key else None
        if prospect_id:
            stats["matched"] += 1
            touched_prospects.add(prospect_id)
        else:
            stats["unmatched"] += 1

        call = calls_by_external_id.get(external_id)
        if call is None:
            started_ms = payload.get("start_timestamp")
            started_at = (
                datetime.fromtimestamp(started_ms / 1000, tz=UTC)
                if isinstance(started_ms, int | float) and started_ms > 0
                else datetime.now(UTC)
            )
            call = Call(
                tenant_id=tenant_id,
                # Imported calls are by definition not ours to attribute to a local Agent
                # row — the platform's agent id is all we have (ADR-012), and
                # create_outbound_call_record's XOR rule is satisfied by setting only it.
                agent_id=None,
                external_agent_id=payload.get("agent_id"),
                # "" rather than null for web calls: the column is NOT NULL, and an empty
                # string reads unambiguously as "this call had no phone number".
                caller_number=(number or "")[:20],
                status="in_progress",
                started_at=started_at,
                external_id=external_id,
                prospect_id=prospect_id,
            )
            db.add(call)
            await db.flush()
            # Keep the prefetch map authoritative: the platform can report the same
            # call_id twice in one history page, and without this the second sighting
            # would insert a duplicate row rather than updating the one just created.
            calls_by_external_id[external_id] = call
            stats["created"] += 1
        else:
            # Heal a row imported (or placed) before its prospect existed in the list.
            # Never overwrite an existing link: the placing code knew better than a
            # phone match does.
            if prospect_id and call.prospect_id is None:
                # cast: the models annotate id columns with SQLAlchemy's UUID type rather
                # than uuid.UUID, so assigning a real uuid.UUID reads as a mismatch. Same
                # repo-wide wart lead_service works around; not this change's to fix.
                call.prospect_id = cast(Any, prospect_id)
            stats["updated"] += 1

        await apply_retell_call_state(db, call, payload)
        await db.commit()
        await _fanout_post_call(db, call, prospect=prospects_by_id.get(call.prospect_id))

    await resync_prospects_from_calls(db, tenant_id, touched_prospects)
    return stats


async def resync_prospects_from_calls(
    db: AsyncSession, tenant_id: uuid.UUID, prospect_ids: set[uuid.UUID]
) -> None:
    """Rebuild call_count, last_called_at and status for the given prospects from their
    Call rows — the settle-up step after a backfill.

    Everything here is *recomputed*, never incremented, because backfill_from_platform is
    re-run routinely: `call_count` gates batch_call_targets, so an inflated count would
    silently make a prospect ineligible for outreach forever — a much worse failure than
    a stale one.

    Status goes through prospect_service.resync_status_from_calls, which unlike the
    per-call classifier is allowed to move a status *down*. That is the point: it is what
    repairs prospects whose status the single-call path got wrong before the whole history
    was available.
    """
    if not prospect_ids:
        return

    from backend.services import prospect_service

    rows = await db.execute(
        select(Call).where(Call.tenant_id == tenant_id, Call.prospect_id.in_(prospect_ids))
    )
    # Keyed on Any for the same UUID-annotation reason as the cast above; every key is a
    # real uuid.UUID at runtime, matched against Prospect.id below.
    calls_by_prospect: dict[Any, list[Call]] = {}
    for call in rows.scalars():
        calls_by_prospect.setdefault(call.prospect_id, []).append(call)

    prospects = await db.execute(select(Prospect).where(Prospect.id.in_(prospect_ids)))
    for prospect in prospects.scalars():
        calls = calls_by_prospect.get(prospect.id, [])
        prospect.call_count = len(calls)
        prospect.last_called_at = max((c.started_at for c in calls), default=None)
        await prospect_service.resync_status_from_calls(db, prospect, calls)
    await db.commit()
