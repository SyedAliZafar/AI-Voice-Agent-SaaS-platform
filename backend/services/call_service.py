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
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.call import Call, Transcript

logger = logging.getLogger(__name__)

# Retell disconnection_reason -> our Call.status. Anything ended and not listed here is
# a normal completion ("resolved"). Source: Retell's call object docs.
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
    "scam_detected",
    "error_user_not_joined",
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
    agent_id: uuid.UUID,
    external_id: str,
    caller_number: str,
) -> Call:
    """Called by test_call_service right after the voice platform confirms an
    outbound call was placed — see module docstring for why creation happens here
    rather than on the call_started webhook.
    """
    call = Call(
        tenant_id=tenant_id,
        agent_id=agent_id,
        caller_number=caller_number,
        status="in_progress",
        started_at=datetime.now(UTC),
        external_id=external_id,
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


async def _write_transcript(db: AsyncSession, call: Call, transcript_text: str) -> None:
    """Upsert a call's transcript. Caller commits."""
    existing = await get_transcript(db, call.id, call.tenant_id)
    if existing:
        existing.full_text = transcript_text
    else:
        db.add(Transcript(call_id=call.id, full_text=transcript_text, turns=[]))


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


async def apply_retell_call_state(
    db: AsyncSession, call: Call, payload: dict[str, Any]
) -> bool:
    """Single writer for terminal call state, shared by the webhook and reconcile paths.

    `payload` is Retell's call object — the nested "call" from a webhook, or the body of
    GET /v2/get-call. Both carry the same fields, which is what lets one function serve
    both. Returns True if anything changed. Caller commits.

    Prefers Retell's own duration_ms over wall-clock arithmetic: a reconcile can run days
    after the call ended, so computing `now - started_at` there would be wildly wrong.
    """
    changed = False

    new_status = _status_for(
        str(payload.get("call_status") or ""), payload.get("disconnection_reason")
    )
    if new_status and call.status != new_status:
        call.status = new_status
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

    transcript_text = payload.get("transcript")
    if isinstance(transcript_text, str) and transcript_text.strip():
        await _write_transcript(db, call, transcript_text)
        changed = True

    return changed


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
    return changed


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
