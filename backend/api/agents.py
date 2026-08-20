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
    AmbientSoundInfo,
    AmbientSoundsResponse,
    LlmModelInfo,
    LlmModelsResponse,
    PlatformAgentCallRequest,
    PlatformAgentCallResponse,
    PlatformAgentInfo,
    PlatformAgentsResponse,
    PlatformAgentVariablesResponse,
    SandboxChatRequest,
    SandboxChatResponse,
    TestCallRequest,
    TestCallResponse,
)
from backend.services import agent_service, llm_service, sandbox_service, test_call_service
from backend.services.retell_adapter import AMBIENT_SOUND_CATALOG

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


@router.get("/ambient-sounds", response_model=AmbientSoundsResponse)
async def list_ambient_sounds(
    tenant_id: uuid.UUID = Depends(get_current_tenant),
):
    """The background-noise options selectable per-agent (Custom LLM path only — see
    test_call_service._provision_custom_llm_agent). Sourced from Retell's own accepted
    values (backend/services/retell_adapter.AMBIENT_SOUND_CATALOG), not hand-maintained
    here — a dashboard-vs-code enum mismatch is exactly how the last three settings on
    this campaign silently did nothing.

    Declared BEFORE /{agent_id} for the same routing reason as /models above.
    """
    return AmbientSoundsResponse(
        options=[AmbientSoundInfo(**o) for o in AMBIENT_SOUND_CATALOG],
        default=settings.retell_ambient_sound,
    )


@router.get("/platform", response_model=PlatformAgentsResponse)
async def list_platform_agents(
    platform: str = "retell",
    tenant_id: uuid.UUID = Depends(get_current_tenant),
):
    """Agents that live on the voice platform itself — including ones built by hand in
    its dashboard that this backend never provisioned (ADR-012).

    Fetched live on every request, not mirrored into our database, so the picker can
    never offer an agent that was renamed or deleted upstream.

    Declared BEFORE /{agent_id} for the same routing reason as /models above.

    Tenant note: `tenant_id` is required for auth but doesn't scope the result — one
    RETELL_API_KEY serves the whole deployment today, so every tenant sees the same
    roster. See ADR-012.
    """
    try:
        agents = await test_call_service.list_platform_agents(platform)
    except test_call_service.TestCallError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ValueError as exc:  # get_adapter on an unknown platform name
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return PlatformAgentsResponse(
        platform=platform, agents=[PlatformAgentInfo(**a) for a in agents]
    )


@router.get(
    "/platform/{external_agent_id}/variables",
    response_model=PlatformAgentVariablesResponse,
)
async def get_platform_agent_variables(
    external_agent_id: str,
    platform: str = "retell",
    tenant_id: uuid.UUID = Depends(get_current_tenant),
):
    """Which `{{placeholders}}` this platform agent's prompt declares (ADR-012).

    Lets the dial form ask for exactly what the agent needs, the same way Retell's own
    dashboard does — and it derives the list the same way, by scanning the prompt, since
    no endpoint reports it.
    """
    try:
        variables = await test_call_service.get_platform_agent_variables(
            external_agent_id, platform
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return PlatformAgentVariablesResponse(external_agent_id=external_agent_id, variables=variables)


@router.post("/platform/call", response_model=PlatformAgentCallResponse)
async def call_platform_agent(
    payload: PlatformAgentCallRequest,
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Dial a number using a platform-native agent (ADR-012).

    Not `/{agent_id}/test-call`: there is no local agent id to put in the path, and the
    two paths differ in more than their argument — this one provisions nothing and our
    conversation engine never runs. Same routing-order reason for living above
    /{agent_id}.
    """
    try:
        result = await test_call_service.place_platform_agent_call(
            db,
            tenant_id,
            payload.external_agent_id,
            payload.to_number,
            platform=payload.platform,
            dynamic_variables=payload.dynamic_variables,
        )
    except test_call_service.TestCallError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return result


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
        result = await test_call_service.place_test_call(db, agent_id, tenant_id, payload.to_number)
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
