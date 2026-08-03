"""Call history and transcript retrieval endpoints."""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import get_current_tenant
from backend.database import get_db
from backend.schemas.call import CallResponse, CallSyncResponse, TranscriptResponse
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
