"""Tool: cancel_appointment — cancels a booking made earlier in the same call.

booking_uid must come from a prior book_appointment/reschedule_appointment result or the
ADR-009 §4c ledger note (retell_ws.py renders it inline as "[booking_uid=...]") — never
invented. This is the fix for outliers.md §5: a real call had the agent claim "let me
cancel the nine AM" with no tool to back that claim, leaving the caller with two live
bookings while believing they had one.

Tracked by the ADR-009 §4c ledger (retell_ws._LEDGER_ARG_KEYS), keyed on booking_uid — a
barge-in re-attempt of the same cancel must not double-fire, same reasoning as
book_appointment/create_lead/send_sms.
"""

from typing import Any

from backend.services.integration_service import IntegrationTimeoutError, cancel_calendar_booking
from backend.tools.base import BaseTool, uncertain_result


class CancelAppointmentTool(BaseTool):
    name = "cancel_appointment"
    description = (
        "Cancel an appointment that was already booked earlier in this call. Requires "
        "the booking_uid from that booking's result or from the 'already completed' "
        "note — never guess or invent a booking_uid."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "booking_uid": {
                "type": "string",
                "description": (
                    "The uid of the booking to cancel, from an earlier "
                    "book_appointment/reschedule_appointment result"
                ),
            },
            "reason": {
                "type": "string",
                "description": "Why the caller is cancelling, if given",
            },
        },
        "required": ["booking_uid"],
    }

    async def handler(self, input: dict, caller_context: dict[str, Any]) -> dict:
        try:
            result = await cancel_calendar_booking(
                booking_uid=input["booking_uid"],
                api_key=caller_context.get("calendar_api_key", ""),
                reason=input.get("reason"),
            )
        except IntegrationTimeoutError:
            # outliers.md §5: a timeout is not a confirmed failure — Cal.com may have
            # cancelled the booking before our client gave up waiting.
            return uncertain_result("cancellation")
        return {
            "cancelled": result.get("status") == "cancelled",
            "booking_uid": input["booking_uid"],
        }
