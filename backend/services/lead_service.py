"""Lead CRUD, prompt assembly, and the retry-scheduler state machine (ADR-011).

retry_state lifecycle:
    paused --start--> scheduled <--> in_flight --success--> succeeded
                          ^              |
                          `---failure----'  (backoff, up to lead_max_attempts)
                          |
                          `--exhausted (attempt cap hit, no success)
    any state --do-not-call--> do_not_call (terminal)

`scheduled` + a due `next_attempt_at` is the only state workers/lead_tasks.py's beat
task acts on. Outcome evaluation (success vs. another retry) happens in
evaluate_call_outcome, called from call_service once a lead's call reaches a terminal
Call.status — not at dispatch time, since the outcome isn't known until the platform
says the call ended.
"""

import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import get_settings
from backend.models.call import Call, Transcript
from backend.models.lead import Lead
from backend.services import agent_service, script_service, test_call_service

settings = get_settings()

ACTIVE_RETRY_STATES = {"paused", "scheduled", "in_flight"}


class LeadDispatchError(Exception):
    """Raised for operator-actionable failures when placing a lead's call — missing
    agent/phone, agent not found. Distinct from a *failed call outcome*, which is a
    normal event the backoff ladder handles, not an exception.
    """


# --- CRUD --------------------------------------------------------------------------


async def create_lead(db: AsyncSession, tenant_id: uuid.UUID, data: dict) -> Lead:
    lead = Lead(tenant_id=tenant_id, **data)
    db.add(lead)
    await db.commit()
    await db.refresh(lead)
    return lead


async def list_leads(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    retry_state: str | None = None,
    status: str | None = None,
    limit: int = 200,
    offset: int = 0,
) -> list[Lead]:
    query = select(Lead).where(Lead.tenant_id == tenant_id)
    if retry_state:
        query = query.where(Lead.retry_state == retry_state)
    if status:
        query = query.where(Lead.status == status)
    query = query.order_by(Lead.created_at.desc()).limit(limit).offset(offset)
    result = await db.execute(query)
    return list(result.scalars().all())


async def count_by_retry_state(db: AsyncSession, tenant_id: uuid.UUID) -> dict[str, int]:
    rows = await db.execute(
        select(Lead.retry_state, func.count())
        .where(Lead.tenant_id == tenant_id)
        .group_by(Lead.retry_state)
    )
    counts = {state: count for state, count in rows.all()}
    counts["total"] = sum(counts.values())
    return counts


async def get_lead(db: AsyncSession, lead_id: uuid.UUID, tenant_id: uuid.UUID) -> Lead | None:
    """Tenant-scoped, router-facing lookup (ADR-001) — another tenant's lead reads as
    None so callers 404 rather than 403.
    """
    result = await db.execute(select(Lead).where(Lead.id == lead_id, Lead.tenant_id == tenant_id))
    return result.scalar_one_or_none()


async def get_lead_unscoped(db: AsyncSession, lead_id: uuid.UUID) -> Lead | None:
    """Tenant-blind lookup — ONLY for trusted internal callers (the Celery scheduler,
    and call_service's outcome hook, both driven by a lead_id the system itself
    produced). Never call this from a router.
    """
    result = await db.execute(select(Lead).where(Lead.id == lead_id))
    return result.scalar_one_or_none()


async def update_lead(
    db: AsyncSession, lead_id: uuid.UUID, tenant_id: uuid.UUID, fields: dict
) -> Lead | None:
    lead = await get_lead(db, lead_id, tenant_id)
    if not lead:
        return None
    for key, value in fields.items():
        setattr(lead, key, value)
    await db.commit()
    await db.refresh(lead)
    return lead


async def delete_lead(db: AsyncSession, lead_id: uuid.UUID, tenant_id: uuid.UUID) -> bool:
    lead = await get_lead(db, lead_id, tenant_id)
    if not lead:
        return False
    await db.delete(lead)
    await db.commit()
    return True


# --- Scheduler state transitions ----------------------------------------------------


def _resolve_tz(lead: Lead) -> ZoneInfo:
    return ZoneInfo(lead.timezone or settings.default_lead_timezone)


def _snap_to_window(local_dt: datetime) -> datetime:
    """Push a local, tz-aware datetime forward to the next Mon-Fri
    business_hours_start..business_hours_end slot. Idempotent: a datetime already
    inside the window is returned unchanged.
    """
    start, end = settings.lead_business_hours_start, settings.lead_business_hours_end
    dt = local_dt
    for _ in range(8):  # a week's worth of weekday/hour rollovers is always enough
        if dt.weekday() >= 5:  # Saturday=5, Sunday=6
            days_to_monday = 7 - dt.weekday()
            dt = (dt + timedelta(days=days_to_monday)).replace(
                hour=start, minute=0, second=0, microsecond=0
            )
            continue
        if dt.hour < start:
            dt = dt.replace(hour=start, minute=0, second=0, microsecond=0)
            continue
        if dt.hour >= end:
            dt = (dt + timedelta(days=1)).replace(hour=start, minute=0, second=0, microsecond=0)
            continue
        return dt
    return dt


def _at_hour_next_slot(local_now: datetime, hour: int) -> datetime:
    """Today at `hour` if that's still ahead of local_now, else tomorrow at `hour`."""
    candidate = local_now.replace(hour=hour, minute=0, second=0, microsecond=0)
    if candidate <= local_now:
        candidate += timedelta(days=1)
    return candidate


def compute_next_attempt(attempt_count: int, now: datetime, tz_name: str) -> datetime:
    """Backoff ladder for the Nth attempt just having failed (attempt_count is the
    lead's attempt_count AFTER that attempt): 1h -> 3h -> next 09:00 -> next 14:00 ->
    +1 day, always snapped into business hours. Returns a UTC datetime.
    """
    tz = ZoneInfo(tz_name)
    local_now = now.astimezone(tz)

    if attempt_count == 1:
        candidate = local_now + timedelta(hours=1)
    elif attempt_count == 2:
        candidate = local_now + timedelta(hours=3)
    elif attempt_count == 3:
        candidate = _at_hour_next_slot(local_now, settings.lead_business_hours_start)
    elif attempt_count == 4:
        candidate = _at_hour_next_slot(local_now, 14)
    else:
        candidate = local_now + timedelta(days=1)

    return _snap_to_window(candidate).astimezone(UTC)


def within_business_hours(lead: Lead, now: datetime) -> bool:
    # Every real caller passes a freshly-built datetime.now(UTC), which is always aware —
    # but a value round-tripped through SQLite (used only in tests; production runs
    # Postgres, which preserves tzinfo on a DateTime(timezone=True) column) comes back
    # naive. .astimezone() on a naive datetime silently assumes the *system's* local
    # timezone rather than UTC, which would misjudge the window on any host that isn't
    # already UTC. Treating a naive input as UTC matches how the rest of this module
    # produces timestamps and removes that footgun for any future caller too.
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    local_now = now.astimezone(_resolve_tz(lead))
    return (
        local_now.weekday() < 5
        and settings.lead_business_hours_start <= local_now.hour < settings.lead_business_hours_end
    )


async def reschedule_to_window(db: AsyncSession, lead: Lead, now: datetime) -> None:
    """A due lead whose slot arrived outside business hours (the scheduler tick was
    delayed, e.g. by downtime) — push it to the next valid window WITHOUT consuming an
    attempt. Distinct from a failed-attempt reschedule, which does consume one.
    """
    lead.next_attempt_at = _snap_to_window(now.astimezone(_resolve_tz(lead))).astimezone(UTC)
    await db.commit()


async def start_lead(db: AsyncSession, lead_id: uuid.UUID, tenant_id: uuid.UUID) -> Lead | None:
    """Arm the scheduler for this lead — the operator's explicit "start calling"
    action (ADR-011: leads are created paused, never auto-armed).
    """
    lead = await get_lead(db, lead_id, tenant_id)
    if not lead:
        return None
    now = datetime.now(UTC)
    lead.retry_state = "scheduled"
    lead.next_attempt_at = _snap_to_window(now.astimezone(_resolve_tz(lead))).astimezone(UTC)
    await db.commit()
    await db.refresh(lead)
    return lead


async def pause_lead(db: AsyncSession, lead_id: uuid.UUID, tenant_id: uuid.UUID) -> Lead | None:
    lead = await get_lead(db, lead_id, tenant_id)
    if not lead:
        return None
    lead.retry_state = "paused"
    lead.next_attempt_at = None
    await db.commit()
    await db.refresh(lead)
    return lead


async def mark_do_not_call(
    db: AsyncSession, lead_id: uuid.UUID, tenant_id: uuid.UUID
) -> Lead | None:
    lead = await get_lead(db, lead_id, tenant_id)
    if not lead:
        return None
    lead.retry_state = "do_not_call"
    lead.next_attempt_at = None
    await db.commit()
    await db.refresh(lead)
    return lead


# --- Dispatch (placing the call) ----------------------------------------------------


def _build_lead_prompt(agent, lead: Lead) -> str:
    parts = []
    if lead.source:
        parts.append(f"Source: {lead.source}")
    if lead.service_requested:
        parts.append(f"Service requested: {lead.service_requested}")
    if lead.budget:
        parts.append(f"Budget: {lead.budget}")
    if lead.city or lead.country:
        parts.append(f"Location: {', '.join(filter(None, [lead.city, lead.country]))}")
    if lead.request_text:
        parts.append(f"Their request, in their own words: {lead.request_text}")
    for key, value in (lead.details or {}).items():
        parts.append(f"{key}: {value}")

    name = lead.business_name or lead.contact_name or "this lead"
    return script_service.build_lead_prompt(
        agent.system_prompt, name, "\n".join(parts), notes=lead.notes
    )


async def _dispatch(
    db: AsyncSession, lead: Lead, tenant_id: uuid.UUID, agent_id: uuid.UUID, to_number: str
) -> dict:
    agent = await agent_service.get_agent(db, agent_id, tenant_id)
    if not agent:
        raise LeadDispatchError("Agent not found")

    prompt = _build_lead_prompt(agent, lead)
    result = await test_call_service.place_test_call(
        db, agent_id, tenant_id, to_number, system_prompt_override=prompt, lead_id=lead.id
    )

    lead.attempt_count += 1
    lead.last_attempt_at = datetime.now(UTC)
    lead.retry_state = "in_flight"
    await db.commit()
    await db.refresh(lead)
    return result


async def call_lead_now(
    db: AsyncSession,
    lead_id: uuid.UUID,
    tenant_id: uuid.UUID,
    agent_id: uuid.UUID | None = None,
    to_number: str | None = None,
) -> dict:
    """Operator-triggered immediate dial, bypassing the schedule. Still goes through
    the normal attempt/outcome bookkeeping so a manual call and a scheduled one are
    indistinguishable to the retry state machine.
    """
    lead = await get_lead(db, lead_id, tenant_id)
    if not lead:
        raise LeadDispatchError("Lead not found")

    resolved_agent_id = agent_id or lead.agent_id
    if not resolved_agent_id:
        raise LeadDispatchError("No agent assigned to this lead")
    resolved_number = to_number or lead.phone
    if not resolved_number:
        raise LeadDispatchError("No phone number on file for this lead")

    return await _dispatch(db, lead, tenant_id, resolved_agent_id, resolved_number)


async def dispatch_scheduled(db: AsyncSession, lead: Lead) -> None:
    """Called by the beat task for a lead whose next_attempt_at is due. Any dispatch
    failure (missing agent/phone, TestCallError from the voice-platform layer) is
    recorded as a failed attempt via the normal backoff path rather than propagated —
    a misconfigured lead must not stall the scheduler tick for every other lead.

    These three failure paths increment attempt_count themselves before calling
    advance_after_failure, because they never reach _dispatch's own increment (no call
    was ever placed) — contrast evaluate_call_outcome's failure branch, which acts on
    a call _dispatch DID place and already counted.
    """
    if not lead.agent_id:
        lead.attempt_count += 1
        await advance_after_failure(db, lead, "dispatch_error: no agent assigned")
        return
    if not lead.phone:
        lead.attempt_count += 1
        await advance_after_failure(db, lead, "dispatch_error: no phone number")
        return

    try:
        await _dispatch(db, lead, lead.tenant_id, lead.agent_id, lead.phone)
    except (LeadDispatchError, test_call_service.TestCallError) as exc:
        lead.attempt_count += 1
        await advance_after_failure(db, lead, f"dispatch_error: {exc}")


# --- Outcome evaluation ---------------------------------------------------------------


async def advance_after_failure(db: AsyncSession, lead: Lead, outcome: str) -> None:
    """Record a failed attempt and either back off to the next slot or exhaust the
    lead. Does NOT increment attempt_count itself — callers whose attempt was already
    counted (a placed call that failed) pass attempt_count as-is; callers where no call
    was ever placed (dispatch_scheduled's early-exit branches) increment first.
    """
    lead.last_outcome = outcome
    if lead.attempt_count >= settings.lead_max_attempts:
        lead.retry_state = "exhausted"
        lead.next_attempt_at = None
    else:
        lead.retry_state = "scheduled"
        lead.next_attempt_at = compute_next_attempt(
            lead.attempt_count, datetime.now(UTC), lead.timezone or settings.default_lead_timezone
        )
    await db.commit()


async def evaluate_call_outcome(db: AsyncSession, call: Call) -> None:
    """Decide whether a just-terminal lead call counts as success ("human answered and
    talked") or another retry is due. Called from call_service._fanout_post_call.

    Guarded on retry_state == "in_flight" so this only ever fires once per attempt:
    call_ended and call_analyzed both reach a terminal Call.status and both call this,
    but the first one to run flips retry_state away from "in_flight", so the second
    is a no-op. The same guard means an operator who paused/do-not-called a lead
    mid-call is respected — the in-flight call's outcome no longer re-arms it.
    """
    if not call.lead_id:
        return
    lead = await get_lead_unscoped(db, call.lead_id)
    if not lead or lead.retry_state != "in_flight":
        return

    transcript_result = await db.execute(select(Transcript).where(Transcript.call_id == call.id))
    transcript = transcript_result.scalar_one_or_none()
    turns = transcript.turns if transcript else []
    caller_turns = sum(1 for t in turns if t.get("role") == "caller")

    # "Human answered and talked": the call reached a real conversational end (not a
    # dial failure) and the other side said at least one thing back — a voicemail
    # pickup or an instant hangup produces zero caller turns and is treated as a
    # failed attempt, not a success.
    success = call.status in ("resolved", "escalated") and caller_turns > 0

    lead.last_outcome = call.status
    if success:
        lead.retry_state = "succeeded"
        lead.status = "contacted"
        lead.next_attempt_at = None
        await db.commit()
    else:
        await advance_after_failure(db, lead, call.status)


# --- Stale in-flight sweep ------------------------------------------------------------


async def stale_in_flight_leads(db: AsyncSession, cutoff: datetime) -> list[Lead]:
    result = await db.execute(
        select(Lead).where(Lead.retry_state == "in_flight", Lead.last_attempt_at < cutoff)
    )
    return list(result.scalars().all())


async def latest_call_for_lead(db: AsyncSession, lead_id: uuid.UUID) -> Call | None:
    result = await db.execute(
        select(Call).where(Call.lead_id == lead_id).order_by(Call.created_at.desc()).limit(1)
    )
    return result.scalar_one_or_none()


async def due_leads(db: AsyncSession, now: datetime, limit: int = 20) -> list[Lead]:
    result = await db.execute(
        select(Lead)
        .where(Lead.retry_state == "scheduled", Lead.next_attempt_at <= now)
        .order_by(Lead.next_attempt_at)
        .limit(limit)
    )
    return list(result.scalars().all())
