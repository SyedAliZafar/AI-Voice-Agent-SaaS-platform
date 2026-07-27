"""Outbound "test call" — dial the operator's own phone so they can hear an
agent's generated sales script live.

Uses Retell's built-in LLM (response_engine "retell-llm") rather than our
custom-LLM websocket, so no tunnel/WS server is required to hear the pitch.
DeepSeek + server-side tools are NOT exercised by this path — see ADR-003 for
the real call-time brain, which this intentionally bypasses for a quick,
low-friction way to audition a script. ADR-002: all Retell HTTP stays behind
the adapter; this service only orchestrates.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import get_settings
from backend.services import agent_service, call_service
from backend.services.retell_adapter import RetellAdapter

settings = get_settings()


class TestCallError(Exception):
    """Raised for operator-actionable failures (missing from-number, etc)."""


async def place_test_call(
    db: AsyncSession,
    agent_id: uuid.UUID,
    to_number: str,
    system_prompt_override: str | None = None,
) -> dict:
    """Place an outbound call for `agent`. By default reads/pushes `agent.system_prompt`.

    `system_prompt_override` lets a caller (e.g. prospect_service's per-company call)
    push a *personalized* variant (base script + [COMPANY BRIEF]) to Retell for just this
    call, without overwriting the agent's base `system_prompt` in the database — the
    campaign script stays the source of truth; personalization is call-time only.
    """
    agent = await agent_service.get_agent(db, agent_id)
    if not agent:
        raise TestCallError("Agent not found")

    if agent.platform != "retell":
        raise TestCallError(
            f"Test calls currently support Retell agents only (this agent is '{agent.platform}')"
        )

    if not settings.retell_from_number:
        raise TestCallError(
            "RETELL_FROM_NUMBER is not set. Run scripts/setup_retell_number.py to import a "
            "Twilio number into Retell, then set RETELL_FROM_NUMBER in .env."
        )

    prompt = system_prompt_override or agent.system_prompt

    adapter = RetellAdapter()
    retell_ids: dict = dict((agent.voice_config or {}).get("retell") or {})

    if retell_ids.get("llm_id"):
        await adapter.update_llm(retell_ids["llm_id"], prompt)
    else:
        retell_ids["llm_id"] = await adapter.create_llm(prompt)

    if not retell_ids.get("agent_id"):
        voice_id = (agent.voice_config or {}).get("voiceId") or settings.retell_default_voice_id
        retell_ids["agent_id"] = await adapter.create_agent_with_llm(
            name=agent.name, llm_id=retell_ids["llm_id"], voice_id=voice_id
        )

    # Persist the external ids so subsequent test calls reuse them instead of
    # re-provisioning, and so a prompt edit only needs an update, not a recreate.
    new_voice_config = {**(agent.voice_config or {}), "retell": retell_ids}
    agent.voice_config = new_voice_config
    await db.commit()
    await db.refresh(agent)

    call_id = await adapter.create_outbound_call(
        from_number=settings.retell_from_number,
        to_number=to_number,
        agent_external_id=retell_ids["agent_id"],
    )

    # Create the Call row now — we have agent_id/tenant_id here, which webhook
    # events alone never carry. See call_service module docstring.
    await call_service.create_outbound_call_record(
        db, agent.tenant_id, agent.id, call_id, to_number
    )

    return {
        "call_id": call_id,
        "from_number": settings.retell_from_number,
        "status": "dialing",
    }
