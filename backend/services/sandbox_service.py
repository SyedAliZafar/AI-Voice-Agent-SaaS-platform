"""Agent testing sandbox — chat with an agent's persona/system_prompt over text,
without spending a real phone call. See CONTEXT.md's "Agent testing sandbox" data flow.

Stateless by design: the client holds the conversation and resends the full history
each turn, exactly the shape llm_service.get_agent_response already takes. No new
table, no session store — a plain request/response wrapper around that call.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import get_settings
from backend.services import agent_service, llm_service

settings = get_settings()


class SandboxError(Exception):
    """Agent not found / not owned by this tenant — mapped to 404 by the router so
    ids stay non-enumerable, matching agent_service.get_agent's own convention."""


async def chat(
    db: AsyncSession,
    agent_id: uuid.UUID,
    tenant_id: uuid.UUID,
    messages: list[dict[str, str]],
    *,
    system_prompt_override: str | None = None,
    model: str | None = None,
    tools_enabled: bool = False,
) -> dict:
    """Run one sandbox turn against `agent`.

    Unlike the live custom-LLM path (test_call_service._provision_custom_llm_agent),
    which rejects system_prompt_override outright because the WS handler reads
    Agent.system_prompt fresh from the DB per call, the sandbox is a plain request —
    the override has an obvious place to live, and trying prompt variants without
    touching the saved agent is the whole point of this feature.

    tools_enabled defaults to False: book_appointment/create_lead genuinely POST to
    Cal.com/HubSpot via integration_service — a text sandbox shouldn't hit those by
    accident. Opt in per request to actually exercise the tool-calling loop.
    """
    agent = await agent_service.get_agent(db, agent_id, tenant_id)
    if not agent:
        raise SandboxError("Agent not found")

    system_prompt = system_prompt_override or agent.system_prompt
    resolved_model = model or agent.llm_model or settings.default_llm_model
    caller_context = {
        "caller_number": "",
        "tenant_id": str(tenant_id),
        "agent_id": str(agent_id),
        "sandbox": True,
    }

    reply = await llm_service.get_agent_response(
        system_prompt,
        messages,
        caller_context,
        model=resolved_model,
        tools_enabled=tools_enabled,
    )

    return {
        "reply": reply,
        "model": resolved_model,
        "tools_enabled": tools_enabled,
        "system_prompt": system_prompt,
    }
