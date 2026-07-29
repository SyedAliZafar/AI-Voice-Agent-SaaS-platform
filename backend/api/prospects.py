"""Prospecting endpoints — discovery, research status, and per-prospect calling.

tenant_id comes from the bearer token via Depends(get_current_tenant) — see
backend/api/deps.py. Every prospect_id arriving here is attacker-controlled, so lookups
go through prospect_service.get_prospect() (tenant-scoped), never get_prospect_unscoped().
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import get_current_tenant
from backend.database import get_db
from backend.schemas.agent import TestCallResponse
from backend.schemas.prospect import (
    CompanyResearch,
    DiscoverRequest,
    ProspectCallRequest,
    ProspectResponse,
    ProspectUpdate,
)
from backend.services import agent_service, prospect_service, script_service, test_call_service
from backend.workers.prospect_tasks import discover_prospects, research_prospect

router = APIRouter()

VALID_OUTREACH_STATUSES = {"not_reached", "reached", "callback", "do_not_call"}


@router.post("/discover", status_code=202)
async def discover(
    payload: DiscoverRequest,
    tenant_id: uuid.UUID = Depends(get_current_tenant),
):
    """Enqueues Agent 1 (Places discovery, auto-chaining Agent 2 research per new
    prospect). Returns immediately — poll GET / to watch rows appear and research
    flip to "ready".
    """
    discover_prospects.delay(
        str(tenant_id), payload.query, payload.location, payload.radius_m, payload.limit
    )
    return {"status": "queued"}


@router.get("", response_model=list[ProspectResponse])
async def list_prospects(
    research_status: str | None = None,
    outreach_status: str | None = None,
    limit: int = 100,
    offset: int = 0,
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    return await prospect_service.list_prospects(
        db, tenant_id, research_status, outreach_status, limit, offset
    )


@router.get("/{prospect_id}", response_model=ProspectResponse)
async def get_prospect(
    prospect_id: uuid.UUID,
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    prospect = await prospect_service.get_prospect(db, prospect_id, tenant_id)
    if not prospect:
        raise HTTPException(status_code=404, detail="Prospect not found")
    return prospect


@router.post("/{prospect_id}/research", status_code=202)
async def rerun_research(
    prospect_id: uuid.UUID,
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    prospect = await prospect_service.get_prospect(db, prospect_id, tenant_id)
    if not prospect:
        raise HTTPException(status_code=404, detail="Prospect not found")

    research_prospect.delay(str(prospect_id))
    return {"status": "queued"}


@router.patch("/{prospect_id}", response_model=ProspectResponse)
async def update_prospect(
    prospect_id: uuid.UUID,
    payload: ProspectUpdate,
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    if payload.outreach_status and payload.outreach_status not in VALID_OUTREACH_STATUSES:
        raise HTTPException(
            status_code=422, detail=f"Invalid outreach_status: {payload.outreach_status}"
        )

    if payload.outreach_status:
        prospect = await prospect_service.set_outreach_status(
            db, prospect_id, tenant_id, payload.outreach_status
        )
    else:
        prospect = await prospect_service.get_prospect(db, prospect_id, tenant_id)

    if not prospect:
        raise HTTPException(status_code=404, detail="Prospect not found")
    return prospect


@router.post("/{prospect_id}/call", response_model=TestCallResponse)
async def call_prospect(
    prospect_id: uuid.UUID,
    payload: ProspectCallRequest,
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Personalizes the given agent's campaign script with this prospect's research
    ([COMPANY BRIEF] injection — script_service.build_prospect_prompt) and places the
    call via the same Retell provisioning path as a plain test call.
    """
    prospect = await prospect_service.get_prospect(db, prospect_id, tenant_id)
    if not prospect:
        raise HTTPException(status_code=404, detail="Prospect not found")
    if prospect.research_status != "ready":
        raise HTTPException(
            status_code=422,
            detail=f"Prospect research is '{prospect.research_status}', not ready yet",
        )

    to_number = payload.to_number or prospect.phone
    if not to_number:
        raise HTTPException(status_code=422, detail="No phone number on file for this prospect")

    agent = await agent_service.get_agent(db, payload.agent_id, tenant_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    research = CompanyResearch.model_validate(prospect.research or {})
    personalized_prompt = script_service.build_prospect_prompt(
        agent.system_prompt, prospect.name, research
    )

    try:
        result = await test_call_service.place_test_call(
            db,
            payload.agent_id,
            tenant_id,
            to_number,
            system_prompt_override=personalized_prompt,
        )
    except test_call_service.TestCallError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    await prospect_service.record_call(db, prospect_id, tenant_id)
    return result
