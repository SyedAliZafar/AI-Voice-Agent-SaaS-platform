"""Tool: book_appointment — schedules a calendar slot for the caller."""

from typing import Any

from backend.services.integration_service import book_calendar_slot
from backend.tools.base import BaseTool


class BookAppointmentTool(BaseTool):
    name = "book_appointment"
    description = "Book a calendar appointment for the caller at a specific date and time."
    input_schema = {
        "type": "object",
        "properties": {
            "start_time": {
                "type": "string",
                "description": "ISO 8601 datetime for the appointment start",
            },
            "duration_min": {"type": "integer", "description": "Duration in minutes"},
            "attendee_email": {"type": "string", "description": "Caller's email address"},
            "attendee_name": {"type": "string", "description": "Caller's name, if given"},
        },
        "required": ["start_time", "duration_min", "attendee_email"],
    }

    async def handler(self, input: dict, caller_context: dict[str, Any]) -> dict:
        # calendar_timezone comes from the agent's book_appointment ToolConfig — it decides
        # how a naive start_time from the LLM is interpreted (see _to_utc_iso). attendee_name
        # is optional in the schema because a caller often never states one; Cal.com v2
        # requires the field, so fall back rather than fail the booking over it.
        result = await book_calendar_slot(
            calendar_id=caller_context.get("calendar_id", ""),
            start_time=input["start_time"],
            duration_min=input["duration_min"],
            attendee_email=input["attendee_email"],
            api_key=caller_context.get("calendar_api_key", ""),
            attendee_name=input.get("attendee_name") or "Caller",
            time_zone=caller_context.get("calendar_timezone", "UTC"),
        )
        return {"booked": True, "confirmation_id": result.get("id")}
