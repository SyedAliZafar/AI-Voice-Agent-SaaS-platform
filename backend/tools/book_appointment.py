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
        },
        "required": ["start_time", "duration_min", "attendee_email"],
    }

    async def handler(self, input: dict, caller_context: dict[str, Any]) -> dict:
        result = await book_calendar_slot(
            calendar_id=caller_context.get("calendar_id", ""),
            start_time=input["start_time"],
            duration_min=input["duration_min"],
            attendee_email=input["attendee_email"],
            api_key=caller_context.get("calendar_api_key", ""),
        )
        return {"booked": True, "confirmation_id": result.get("id")}
