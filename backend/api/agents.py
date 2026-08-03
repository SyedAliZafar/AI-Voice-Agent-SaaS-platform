"""CRUD endpoints for agent configuration."""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import get_current_tenant
from backend.config import get_settings
from backend.database import get_db
from backend.schemas.agent import (
    AgentCreate,
    AgentResponse,
    AgentUpdate,
    LlmModelInfo,
    LlmModelsResponse,
    SandboxChatRequest,
    SandboxChatResponse,
    TestCallRequest,
    TestCallResponse,
)
from backend.services import agent_service, llm_service, sandbox_service, test_call_service

router = APIRouter()
settings = get_settings()


@router.get("/models", response_model=LlmModelsResponse)
async def list_llm_models(
    tenant_id: uuid.UUID = Depends(get_current_tenant),
):
    """The models selectable per-agent (frontend's Conversation-engine model dropdown).

    Declared BEFORE /{agent_id} — same route-ordering trap POST /api/calls/sync
    documents in backend/api/calls.py: "models" would otherwise be captured by the
    uuid.UUID path param and 422.
    """
    configured = llm_service.provider_configured_status()
    return LlmModelsResponse(
        models=[
            LlmModelInfo(
                id=m["id"],
                label=m["label"],
                provider=m["provider"],
                configured=configured.get(m["provider"], False),
            )
            for m in llm_service.MODEL_CATALOG
        ],
        default=settings.default_llm_model,
    )


@router.get("", response_model=list[AgentResponse])
async def list_agents(
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    return await agent_service.list_agents(db, tenant_id)


@router.post("", response_model=AgentResponse, status_code=201)
async def create_agent(
    payload: AgentCreate,
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    return await agent_service.create_agent(db, tenant_id, payload)


@router.get("/{agent_id}", response_model=AgentResponse)
async def get_agent(
    agent_id: uuid.UUID,    
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    agent = await agent_service.get_agent(db, agent_id, tenant_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


@router.patch("/{agent_id}", response_model=AgentResponse)
async def update_agent(
    agent_id: uuid.UUID,
    payload: AgentUpdate,
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    agent = await agent_service.update_agent(db, agent_id, tenant_id, payload)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


@router.delete("/{agent_id}", status_code=204)
async def delete_agent(
    agent_id: uuid.UUID,
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    await agent_service.delete_agent(db, agent_id, tenant_id)


@router.post("/{agent_id}/test-call", response_model=TestCallResponse)
async def test_call(
    agent_id: uuid.UUID,
    payload: TestCallRequest,
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Dial the operator's own phone with the agent's current script (Retell built-in
    LLM — see backend/services/test_call_service.py for why this bypasses the
    configured conversation model).
    """
    try:
        result = await test_call_service.place_test_call(
            db, agent_id, tenant_id, payload.to_number
        )
    except test_call_service.TestCallError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return result


@router.post("/{agent_id}/sandbox-chat", response_model=SandboxChatResponse)
async def sandbox_chat(
    agent_id: uuid.UUID,
    payload: SandboxChatRequest,
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Chat with an agent's persona/system_prompt over text — no phone call, no
    telephony spend. See backend/services/sandbox_service.py.
    """
    try:
        result = await sandbox_service.chat(
            db,
            agent_id,
            tenant_id,
            [m.model_dump() for m in payload.messages],
            system_prompt_override=payload.system_prompt_override,
            model=payload.model,
            tools_enabled=payload.tools_enabled,
        )
    except sandbox_service.SandboxError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except llm_service.LLMConfigError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return result
