"""Lead endpoints — CRUD, scheduler control (start/pause/do-not-call), and manual
call-now (ADR-011).

tenant_id comes from the bearer token via Depends(get_current_tenant) — see
backend/api/deps.py. Every lead_id arriving here is attacker-controlled, so lookups go
through lead_service.get_lead() (tenant-scoped), never get_lead_unscoped().
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import get_current_tenant
from backend.database import get_db
from backend.schemas.lead import LeadCallRequest, LeadCreate, LeadResponse, LeadStats, LeadUpdate
from backend.services import lead_service, test_call_service

router = APIRouter()

VALID_STATUSES = {"new", "contacted", "booked", "not_interested", "unreachable"}


@router.post("", response_model=LeadResponse, status_code=201)
async def create_lead(
    payload: LeadCreate,
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """New leads land `retry_state="paused"` (the model default) — the operator arms
    calling explicitly via POST /{id}/start, never automatically on create.
    """
    lead = await lead_service.create_lead(db, tenant_id, payload.model_dump())
    return lead


@router.get("", response_model=list[LeadResponse])
async def list_leads(
    retry_state: str | None = None,
    status: str | None = None,
    limit: int = 200,
    offset: int = 0,
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    return await lead_service.list_leads(db, tenant_id, retry_state, status, limit, offset)


@router.get("/stats", response_model=LeadStats)
async def lead_stats(
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    counts = await lead_service.count_by_retry_state(db, tenant_id)
    return LeadStats(**{k: v for k, v in counts.items() if k in LeadStats.model_fields})


@router.get("/{lead_id}", response_model=LeadResponse)
async def get_lead(
    lead_id: uuid.UUID,
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    lead = await lead_service.get_lead(db, lead_id, tenant_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    return lead


@router.patch("/{lead_id}", response_model=LeadResponse)
async def update_lead(
    lead_id: uuid.UUID,
    payload: LeadUpdate,
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    if payload.status and payload.status not in VALID_STATUSES:
        raise HTTPException(status_code=422, detail=f"Invalid status: {payload.status}")

    fields = payload.model_dump(exclude_unset=True)
    lead = await lead_service.update_lead(db, lead_id, tenant_id, fields)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    return lead


@router.delete("/{lead_id}", status_code=204)
async def delete_lead(
    lead_id: uuid.UUID,
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    deleted = await lead_service.delete_lead(db, lead_id, tenant_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Lead not found")


@router.post("/{lead_id}/start", response_model=LeadResponse)
async def start_lead(
    lead_id: uuid.UUID,
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    lead = await lead_service.start_lead(db, lead_id, tenant_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    return lead


@router.post("/{lead_id}/pause", response_model=LeadResponse)
async def pause_lead(
    lead_id: uuid.UUID,
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    lead = await lead_service.pause_lead(db, lead_id, tenant_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    return lead


@router.post("/{lead_id}/do-not-call", response_model=LeadResponse)
async def do_not_call_lead(
    lead_id: uuid.UUID,
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    lead = await lead_service.mark_do_not_call(db, lead_id, tenant_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    return lead


@router.post("/{lead_id}/call")
async def call_lead(
    lead_id: uuid.UUID,
    payload: LeadCallRequest,
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Dial this lead right now, outside the schedule — still goes through the normal
    attempt/outcome bookkeeping (see lead_service.call_lead_now).
    """
    try:
        return await lead_service.call_lead_now(
            db, lead_id, tenant_id, agent_id=payload.agent_id, to_number=payload.to_number
        )
    except lead_service.LeadDispatchError as exc:
        detail = str(exc)
        status_code = 404 if detail == "Lead not found" else 422
        raise HTTPException(status_code=status_code, detail=detail) from exc
    except test_call_service.TestCallError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
