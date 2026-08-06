"""Tool: send_sms — sends a text confirmation via Twilio."""

from typing import Any

from backend.tools.base import BaseTool


class SendSmsTool(BaseTool):
    name = "send_sms"
    description = "Send an SMS confirmation or follow-up link to the caller."
    input_schema = {
        "type": "object",
        "properties": {
            "to_number": {"type": "string"},
            "message": {"type": "string"},
        },
        "required": ["to_number", "message"],
    }

    async def handler(self, input: dict, caller_context: dict[str, Any]) -> dict:
        # Wire up Twilio's Messages API here
        raise NotImplementedError(
            "send_sms has no real Twilio integration wired up yet; "
            "it must not report success to the caller."
        )
