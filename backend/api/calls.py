"""Call history and transcript retrieval endpoints."""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.schemas.call import CallResponse, TranscriptResponse
from backend.services import call_service

router = APIRouter()


@router.get("", response_model=list[CallResponse])
async def list_calls(
    tenant_id: uuid.UUID,
    agent_id: uuid.UUID | None = None,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
):
    return await call_service.list_calls(db, tenant_id, agent_id, status, limit, offset)


@router.get("/{call_id}", response_model=CallResponse)
async def get_call(call_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    call = await call_service.get_call(db, call_id)
    if not call:
        raise HTTPException(status_code=404, detail="Call not found")
    return call


@router.get("/{call_id}/transcript", response_model=TranscriptResponse)
async def get_transcript(call_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    transcript = await call_service.get_transcript(db, call_id)
    if not transcript:
        raise HTTPException(status_code=404, detail="Transcript not found")
    return transcript
