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
"""

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.call import Call, Transcript

logger = logging.getLogger(__name__)


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


async def handle_transcript_update(
    db: AsyncSession, external_call_id: str, transcript_text: str
) -> None:
    call = await get_call_by_external_id(db, external_call_id)
    if not call:
        logger.info(
            "transcript_update for unknown call, ignoring",
            extra={"external_call_id": external_call_id},
        )
        return

    existing = await get_transcript(db, call.id, call.tenant_id)
    if existing:
        existing.full_text = transcript_text
    else:
        db.add(Transcript(call_id=call.id, full_text=transcript_text, turns=[]))
    await db.commit()


async def handle_call_ended(db: AsyncSession, external_call_id: str) -> None:
    call = await get_call_by_external_id(db, external_call_id)
    if not call:
        logger.info(
            "call_ended for unknown call, ignoring",
            extra={"external_call_id": external_call_id},
        )
        return

    call.status = "resolved"  # no richer signal available yet to distinguish outcomes
    now = datetime.now(UTC)
    started_at = call.started_at if call.started_at.tzinfo else call.started_at.replace(tzinfo=UTC)
    call.duration_sec = max(0, int((now - started_at).total_seconds()))
    await db.commit()
