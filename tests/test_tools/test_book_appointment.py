"""Tests for the book_appointment tool handler."""

from unittest.mock import AsyncMock, patch

import pytest

from backend.tools.book_appointment import BookAppointmentTool


@pytest.mark.asyncio
async def test_book_appointment_success():
    tool = BookAppointmentTool()
    mock_result = {"id": "booking_789"}

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

    assert result == {"booked": True, "confirmation_id": "booking_789"}


def test_tool_definition_shape():
    tool = BookAppointmentTool()
    definition = tool.to_definition()

    assert definition["name"] == "book_appointment"
    assert "start_time" in definition["input_schema"]["properties"]
    assert "attendee_email" in definition["input_schema"]["required"]
