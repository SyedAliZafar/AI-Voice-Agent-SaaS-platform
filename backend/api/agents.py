"""CRUD endpoints for agent configuration."""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.schemas.agent import (
    AgentCreate,
    AgentResponse,
    AgentUpdate,
    TestCallRequest,
    TestCallResponse,
)
from backend.services import agent_service, test_call_service

router = APIRouter()


@router.get("", response_model=list[AgentResponse])
async def list_agents(tenant_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    return await agent_service.list_agents(db, tenant_id)


@router.post("", response_model=AgentResponse, status_code=201)
async def create_agent(
    tenant_id: uuid.UUID, payload: AgentCreate, db: AsyncSession = Depends(get_db)
):
    return await agent_service.create_agent(db, tenant_id, payload)


@router.get("/{agent_id}", response_model=AgentResponse)
async def get_agent(agent_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    agent = await agent_service.get_agent(db, agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


@router.patch("/{agent_id}", response_model=AgentResponse)
async def update_agent(
    agent_id: uuid.UUID, payload: AgentUpdate, db: AsyncSession = Depends(get_db)
):
    agent = await agent_service.update_agent(db, agent_id, payload)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


@router.delete("/{agent_id}", status_code=204)
async def delete_agent(agent_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    await agent_service.delete_agent(db, agent_id)


@router.post("/{agent_id}/test-call", response_model=TestCallResponse)
async def test_call(
    agent_id: uuid.UUID, payload: TestCallRequest, db: AsyncSession = Depends(get_db)
):
    """Dial the operator's own phone with the agent's current script (Retell built-in
    LLM — see backend/services/test_call_service.py for why this bypasses DeepSeek).
    """
    try:
        result = await test_call_service.place_test_call(db, agent_id, payload.to_number)
    except test_call_service.TestCallError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return result
