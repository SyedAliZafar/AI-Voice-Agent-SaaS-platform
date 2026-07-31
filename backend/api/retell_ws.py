"""Retell Custom LLM WebSocket — Retell dials in here during a live call and relays
transcript turns; we answer using DeepSeek + server-side tools (ADR-003), replacing
Retell's own hosted LLM for agents with Agent.use_custom_llm=True.

Protocol: docs.retellai.com/api-references/llm-websocket. Retell appends the call's own
call_id to whatever base URL we registered via
RetellAdapter.create_agent_with_custom_llm's llm_websocket_url — see
backend/services/test_call_service.py's _provision_custom_llm_agent — so this route's
{call_id} path param is filled in by Retell itself, not something we template.

Tenant/agent resolution: Retell's frames carry only call_id, no auth header (see
backend/api/deps.py's docstring on why HTTP auth can't apply here). We resolve
tenant_id/agent_id by looking the Call row up by external_id — the same chain
call_service already uses for webhook events — which only works for calls this backend
originated (outbound-only today, per call_service's module docstring).

Scope note (see phase0.md "Files to look at next"): non-streaming — one blocking
llm_service.get_agent_response() call per turn, not incremental content chunks. Tool
execution stays entirely inside that call (invisible to Retell) per ADR-003; Retell's
own tool_call_invocation/tool_call_result message types aren't used here.
"""

import logging
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from backend.database import AsyncSessionLocal
from backend.services import agent_service, call_service, llm_service

logger = logging.getLogger(__name__)

router = APIRouter()

_ROLE_MAP = {"agent": "assistant", "user": "user"}


def _to_conversation_history(transcript: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Retell's transcript uses role "agent"/"user"; llm_service.get_agent_response
    expects OpenAI-style "assistant"/"user"."""
    return [
        {
            "role": _ROLE_MAP.get(turn.get("role", "user"), "user"),
            "content": turn.get("content", ""),
        }
        for turn in transcript
    ]


@router.websocket("/llm-websocket/{call_id}")
async def llm_websocket(websocket: WebSocket, call_id: str) -> None:
    await websocket.accept()

    async with AsyncSessionLocal() as db:
        call = await call_service.get_call_by_external_id(db, call_id)
        if not call:
            logger.warning("llm_websocket: unknown call_id, closing", extra={"call_id": call_id})
            await websocket.close(code=1008)
            return

        # call.agent_id/tenant_id are real uuid.UUID at runtime; the type: ignore is for
        # a pre-existing annotation gap (Mapped[UUID] instead of Mapped[uuid.UUID]) that
        # spans models/call.py and models/agent.py, not something specific to this line.
        agent = await agent_service.get_agent(db, call.agent_id, call.tenant_id)  # type: ignore[arg-type]
        if not agent:
            logger.warning(
                "llm_websocket: call has no resolvable agent, closing",
                extra={"call_id": call_id, "agent_id": str(call.agent_id)},
            )
            await websocket.close(code=1008)
            return

        system_prompt = agent.system_prompt
        caller_context = {
            "caller_number": call.caller_number,
            "tenant_id": str(call.tenant_id),
            "agent_id": str(call.agent_id),
        }

    # Required as the first message per Retell's protocol.
    await websocket.send_json(
        {
            "response_type": "config",
            "config": {
                "auto_reconnect": True,
                "call_details": True,
                "transcript_with_tool_calls": False,
            },
        }
    )

    try:
        while True:
            data = await websocket.receive_json()
            interaction_type = data.get("interaction_type")

            if interaction_type == "ping_pong":
                await websocket.send_json(
                    {"response_type": "ping_pong", "timestamp": data.get("timestamp")}
                )
            elif interaction_type in ("response_required", "reminder_required"):
                conversation_history = _to_conversation_history(data.get("transcript", []))
                text = await llm_service.get_agent_response(
                    system_prompt, conversation_history, caller_context
                )
                await websocket.send_json(
                    {
                        "response_type": "response",
                        "response_id": data.get("response_id"),
                        "content": text,
                        "content_complete": True,
                        "end_call": False,
                    }
                )
            # call_details / update_only: no response required, nothing to do.
    except WebSocketDisconnect:
        pass
