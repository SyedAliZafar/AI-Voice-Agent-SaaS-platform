"""Call history and transcript retrieval endpoints."""

import uuid

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import get_current_tenant
from backend.database import get_db
from backend.schemas.call import (
    CallEventResponse,
    CallResponse,
    CallSyncResponse,
    TranscriptResponse,
)
from backend.services import call_service
from backend.services.retell_adapter import RetellAdapter

router = APIRouter()


@router.post("/sync", response_model=CallSyncResponse)
async def sync_calls(
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Reconcile every still-in_progress call against the voice platform.

    Webhooks are the primary path, but they only work when Retell can reach us — no
    tunnel, an unset PUBLIC_BASE_URL, or a tunnel that restarted mid-call all mean a
    call_ended is lost and the row is stranded at in_progress forever. This pulls
    authoritative state (status, duration, transcript, sentiment) from the platform and
    repairs those rows.

    Declared before /{call_id} so "sync" isn't captured as a call id by the path param.
    """
    updated = await call_service.reconcile_stale_calls(db, tenant_id, RetellAdapter())
    return CallSyncResponse(updated=updated)


@router.post("/{call_id}/end", response_model=CallResponse)
async def end_call(
    call_id: uuid.UUID,
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Hang up a live call immediately — the emergency stop.

    Tenant-scoped like every other route here, so one tenant can't hang up another's
    call. For the case where this API isn't running at all (which is exactly when an
    operator most needs to stop a call), use `scripts/kill_calls.py` instead — it talks
    to Retell directly and needs nothing but the API key.

    Returns the call row after the post-hangup reconcile. It may still read in_progress
    if Retell hadn't finalized the call yet — the hangup has still happened, and the
    call_ended webhook (or POST /sync) settles the row shortly after.
    """
    call = await call_service.get_call(db, call_id, tenant_id)
    if not call:
        raise HTTPException(status_code=404, detail="Call not found")
    if not call.external_id:
        raise HTTPException(
            status_code=422, detail="Call was never placed on the platform — nothing to hang up"
        )

    try:
        await call_service.end_call(db, call, RetellAdapter())
    except httpx.HTTPError as exc:
        # The hangup itself failed — never report success for this, or an operator walks
        # away believing a live call was stopped when it is still talking.
        raise HTTPException(
            status_code=502, detail=f"Voice platform refused the hangup: {exc}"
        ) from exc
    return call


@router.get("", response_model=list[CallResponse])
async def list_calls(
    agent_id: uuid.UUID | None = None,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    return await call_service.list_calls(db, tenant_id, agent_id, status, limit, offset)


@router.get("/{call_id}", response_model=CallResponse)
async def get_call(
    call_id: uuid.UUID,
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    call = await call_service.get_call(db, call_id, tenant_id)
    if not call:
        raise HTTPException(status_code=404, detail="Call not found")
    return call


@router.get("/{call_id}/transcript", response_model=TranscriptResponse)
async def get_transcript(
    call_id: uuid.UUID,
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    transcript = await call_service.get_transcript(db, call_id, tenant_id)
    if not transcript:
        raise HTTPException(status_code=404, detail="Transcript not found")
    return transcript


@router.get("/{call_id}/events", response_model=list[CallEventResponse])
async def get_call_events(
    call_id: uuid.UUID,
    limit: int = 200,
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """What the agent actually did during this call: every tool dispatch and its result,
    each turn's LLM timings, an IVR auto-hangup.

    These rows have been written since ADR-009 but had no reader — every phase4/outliers
    investigation in this repo got at them by querying Postgres by hand. The trail is the
    only place some of that is recorded at all: a "dispatched" tool_call row survives a
    barge-in cancelling the turn that made it, and an ivr_hangup is otherwise
    indistinguishable from a prospect who hung up early.

    404s on an unknown call rather than returning [] — "this call has no events" and
    "this call doesn't exist" are different answers, and only one of them means something
    is wrong. Empty is a perfectly normal answer for a hosted-LLM call, which runs on
    Retell's brain and never reaches the code that writes these.
    """
    call = await call_service.get_call(db, call_id, tenant_id)
    if not call:
        raise HTTPException(status_code=404, detail="Call not found")
    return await call_service.list_call_events(db, call_id, tenant_id, limit)
