"""Tool: reschedule_appointment — moves a booking made earlier in the same call to a
new time.

One atomic Cal.com call, not a composed cancel-then-book_appointment flow — that
composition would reintroduce a real race (cancel succeeds, rebooking fails, caller
loses the appointment entirely), strictly worse than the outliers.md §5 bug this exists
to fix. See integration_service.reschedule_calendar_booking's docstring: the result's
booking_uid is a NEW value, not the one passed in — Cal.com supersedes the original
booking rather than mutating it in place. Return it so the ledger (retell_ws.py) can
carry the current identifier forward for any further action on this appointment in the
same call.

Tracked by the ADR-009 §4c ledger, keyed on the (old) booking_uid it was asked to act
on — this also means a genuine second reschedule of the same appointment isn't blocked:
it would use the NEW uid from this call's own result, a different ledger key.
"""

from typing import Any

from backend.services.integration_service import (
    IntegrationTimeoutError,
    reschedule_calendar_booking,
)
from backend.tools.base import BaseTool, uncertain_result


class RescheduleAppointmentTool(BaseTool):
    name = "reschedule_appointment"
    description = (
        "Move an appointment that was already booked earlier in this call to a new "
        "time. Requires the booking_uid from that booking's result or the 'already "
        "completed' note — never guess or invent a booking_uid. Do not call "
        "check_availability first for a reschedule; Cal.com validates the new time as "
        "part of this call."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "booking_uid": {
                "type": "string",
                "description": (
                    "The uid of the booking to move, from an earlier "
                    "book_appointment/reschedule_appointment result"
                ),
            },
            "new_start_time": {
                "type": "string",
                "description": "ISO 8601 datetime for the new appointment start",
            },
        },
        "required": ["booking_uid", "new_start_time"],
    }

    async def handler(self, input: dict, caller_context: dict[str, Any]) -> dict:
        try:
            result = await reschedule_calendar_booking(
                booking_uid=input["booking_uid"],
                new_start_time=input["new_start_time"],
                api_key=caller_context.get("calendar_api_key", ""),
                time_zone=caller_context.get("calendar_timezone", "UTC"),
            )
        except IntegrationTimeoutError:
            # outliers.md §5: this exact case happened on a real call — the model
            # claimed success after a bare error from a timed-out reschedule that had
            # actually gone through server-side. A timeout is not a confirmed failure.
            return uncertain_result("reschedule")
        return {
            "rescheduled": True,
            "confirmation_id": result.get("id"),
            "booking_uid": result.get("uid"),
        }
