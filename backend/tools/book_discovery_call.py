"""Tool: book_discovery_call — captures a caller's contact info for a follow-up
discovery call with Ali. Validation-pass agent (hvac-solar-outbound-knowledge-v1.md) —
no real calendar integration; the captured info is the return value, and the existing
generic CallEvent(event_type="tool_call") audit trail (llm_service._execute_tool_calls'
on_tool_event, wired in retell_ws.py) is the log. No new table or file needed for that.
"""

from typing import Any

from backend.tools.base import BaseTool


class BookDiscoveryCallTool(BaseTool):
    name = "book_discovery_call"
    description = (
        "Capture the caller's contact info to book a discovery call with Ali. Use once "
        "the caller has agreed to a follow-up — this does not check calendar "
        "availability or send a real invite."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Caller's name"},
            "phone": {"type": "string", "description": "Caller's phone number"},
            "preferred_time": {
                "type": "string",
                "description": "Caller's preferred day/time for the discovery call, as stated",
            },
        },
        "required": ["name", "phone", "preferred_time"],
    }

    async def handler(self, input: dict, caller_context: dict[str, Any]) -> dict:
        return {
            "captured": True,
            "name": input["name"],
            "phone": input["phone"],
            "preferred_time": input["preferred_time"],
        }
