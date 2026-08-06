"""Tests for the cancel_appointment tool handler (outliers.md §5)."""

from unittest.mock import AsyncMock, patch

import pytest

from backend.services.integration_service import IntegrationTimeoutError
from backend.tools.cancel_appointment import CancelAppointmentTool


@pytest.mark.asyncio
async def test_cancel_appointment_success():
    tool = CancelAppointmentTool()
    mock_result = {"id": 23454702, "uid": "abc123uid", "status": "cancelled"}

    with patch(
        "backend.tools.cancel_appointment.cancel_calendar_booking",
        AsyncMock(return_value=mock_result),
    ) as mock_cancel:
        result = await tool.handler(
            input={"booking_uid": "abc123uid", "reason": "caller changed plans"},
            caller_context={"calendar_api_key": "key"},
        )

    mock_cancel.assert_awaited_once_with(
        booking_uid="abc123uid", api_key="key", reason="caller changed plans"
    )
    assert result == {"cancelled": True, "booking_uid": "abc123uid"}


@pytest.mark.asyncio
async def test_reason_is_optional():
    tool = CancelAppointmentTool()
    mock_result = {"status": "cancelled"}

    with patch(
        "backend.tools.cancel_appointment.cancel_calendar_booking",
        AsyncMock(return_value=mock_result),
    ) as mock_cancel:
        await tool.handler(
            input={"booking_uid": "abc123uid"}, caller_context={"calendar_api_key": "key"}
        )

    assert mock_cancel.call_args.kwargs["reason"] is None


@pytest.mark.asyncio
async def test_cancelled_is_false_when_status_does_not_confirm_it():
    """Don't tell the caller a cancellation succeeded unless Cal.com's own result says
    so — same honesty rule as book_appointment never claiming success without a real
    confirmation id."""
    tool = CancelAppointmentTool()
    mock_result = {"status": "accepted"}  # not "cancelled" for whatever reason

    with patch(
        "backend.tools.cancel_appointment.cancel_calendar_booking",
        AsyncMock(return_value=mock_result),
    ):
        result = await tool.handler(
            input={"booking_uid": "abc123uid"}, caller_context={"calendar_api_key": "key"}
        )

    assert result["cancelled"] is False


@pytest.mark.asyncio
async def test_timeout_returns_uncertain_result_not_a_raised_error():
    """outliers.md §5: a timeout is not a confirmed failure — Cal.com may have
    cancelled the booking before our client gave up waiting."""
    tool = CancelAppointmentTool()

    with patch(
        "backend.tools.cancel_appointment.cancel_calendar_booking",
        AsyncMock(side_effect=IntegrationTimeoutError("timed out")),
    ):
        result = await tool.handler(
            input={"booking_uid": "abc123uid"}, caller_context={"calendar_api_key": "key"}
        )

    assert result["status"] == "uncertain"
    assert "cancellation" in result["instruction"]


def test_tool_definition_shape():
    tool = CancelAppointmentTool()
    definition = tool.to_definition()

    assert definition["name"] == "cancel_appointment"
    assert "booking_uid" in definition["input_schema"]["properties"]
    assert definition["input_schema"]["required"] == ["booking_uid"]
