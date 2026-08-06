"""Tool: check_availability — is a given time free, without booking anything.

Read-only counterpart to book_appointment. Deliberately NOT tracked by retell_ws.py's
completed-tool-call ledger (ADR-009 §4c): repeating a read is harmless, and the same
reasoning that excludes lookup_customer applies here — telling the model not to re-check
availability would be actively wrong, since the answer can change during a call.
"""

from typing import Any

from backend.services.integration_service import check_calendar_availability
from backend.tools.base import BaseTool


class CheckAvailabilityTool(BaseTool):
    name = "check_availability"
    description = (
        "Check whether a specific date and time is free on the calendar, without booking "
        "anything. Call this before telling the caller a time is available or unavailable, "
        "and before calling book_appointment. If the time is taken, this also returns "
        "nearby alternative times you can offer instead."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "start_time": {
                "type": "string",
                "description": "ISO 8601 datetime of the slot to check",
            },
        },
        "required": ["start_time"],
    }

    async def handler(self, input: dict, caller_context: dict[str, Any]) -> dict:
        # Reads the same calendar_id/calendar_api_key/calendar_timezone that
        # book_appointment does — retell_ws.py flattens every ToolConfig row into one
        # caller_context regardless of tool_type, so the existing book_appointment
        # ToolConfig row already supplies these. No separate config row is needed.
        return await check_calendar_availability(
            calendar_id=caller_context.get("calendar_id", ""),
            start_time=input["start_time"],
            api_key=caller_context.get("calendar_api_key", ""),
            time_zone=caller_context.get("calendar_timezone", "UTC"),
        )
