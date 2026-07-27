"""Tool: transfer_call — escalates to a human agent.

ADR: this is the most important tool in the system. The LLM should call
this generously rather than risk a bad automated response. Guardrails
in the system prompt define WHEN to escalate; this tool just executes it.
"""

from typing import Any

from backend.tools.base import BaseTool


class TransferCallTool(BaseTool):
    name = "transfer_call"
    description = (
        "Transfer the active call to a human agent. Use when the caller explicitly "
        "asks for a human, when you cannot resolve their issue, or when the "
        "conversation involves something outside your scope."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "reason": {"type": "string", "description": "Why this call is being escalated"},
        },
        "required": ["reason"],
    }

    async def handler(self, input: dict, caller_context: dict[str, Any]) -> dict:
        # Wire up your voice platform's call-transfer API here (Retell/Vapi
        # both expose a transfer/forward action via their call control API)
        return {"transferred": True, "reason": input["reason"]}
