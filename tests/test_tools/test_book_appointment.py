"""Tests for the book_appointment tool handler."""

from unittest.mock import AsyncMock, patch

import pytest

from backend.services.integration_service import IntegrationTimeoutError
from backend.tools.book_appointment import BookAppointmentTool


@pytest.mark.asyncio
async def test_book_appointment_success():
    tool = BookAppointmentTool()
    # uid is what cancel_appointment/reschedule_appointment need to act on this booking
    # later in the same call (outliers.md §5) — must survive into the tool's own result,
    # not just the numeric id.
    mock_result = {"id": "booking_789", "uid": "abc123uid"}

    with patch(
        "backend.tools.book_appointment.book_calendar_slot",
        AsyncMock(return_value=mock_result),
    ):
        result = await tool.handler(
            input={
                "start_time": "2026-07-23T14:00:00Z",
                "duration_min": 30,
                "attendee_email": "caller@example.com",
            },
            caller_context={"calendar_id": "cal_1", "calendar_api_key": "key"},
        )

    assert result == {
        "booked": True,
        "confirmation_id": "booking_789",
        "booking_uid": "abc123uid",
    }


@pytest.mark.asyncio
async def test_timeout_returns_uncertain_result_not_a_raised_error():
    """outliers.md §5: a timeout is not a confirmed failure. The handler must catch
    IntegrationTimeoutError and return an uncertain result, not let a bare exception
    propagate (which would read as a confirmed failure to _execute_tool_calls)."""
    tool = BookAppointmentTool()

    with patch(
        "backend.tools.book_appointment.book_calendar_slot",
        AsyncMock(side_effect=IntegrationTimeoutError("timed out")),
    ):
        result = await tool.handler(
            input={
                "start_time": "2026-07-23T14:00:00Z",
                "duration_min": 30,
                "attendee_email": "caller@example.com",
            },
            caller_context={"calendar_id": "cal_1", "calendar_api_key": "key"},
        )

    assert result["status"] == "uncertain"
    assert "booking" in result["instruction"]


def test_tool_definition_shape():
    tool = BookAppointmentTool()
    definition = tool.to_definition()

    assert definition["name"] == "book_appointment"
    assert "start_time" in definition["input_schema"]["properties"]
    assert "attendee_email" in definition["input_schema"]["required"]
