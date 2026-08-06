"""Tests for the reschedule_appointment tool handler (outliers.md §5)."""

from unittest.mock import AsyncMock, patch

import pytest

from backend.services.integration_service import IntegrationTimeoutError
from backend.tools.reschedule_appointment import RescheduleAppointmentTool


@pytest.mark.asyncio
async def test_reschedule_appointment_success():
    tool = RescheduleAppointmentTool()
    # The new uid genuinely differs from what was passed in — confirmed against a real
    # Cal.com reschedule, not assumed (integration_service.reschedule_calendar_booking's
    # docstring). The tool's result must surface the NEW uid, not echo the old one.
    mock_result = {"id": 23458118, "uid": "new-uid-issued-by-calcom"}

    with patch(
        "backend.tools.reschedule_appointment.reschedule_calendar_booking",
        AsyncMock(return_value=mock_result),
    ) as mock_reschedule:
        result = await tool.handler(
            input={"booking_uid": "old-uid", "new_start_time": "2026-08-10T10:00:00"},
            caller_context={
                "calendar_api_key": "key",
                "calendar_timezone": "Europe/Berlin",
            },
        )

    mock_reschedule.assert_awaited_once_with(
        booking_uid="old-uid",
        new_start_time="2026-08-10T10:00:00",
        api_key="key",
        time_zone="Europe/Berlin",
    )
    assert result == {
        "rescheduled": True,
        "confirmation_id": 23458118,
        "booking_uid": "new-uid-issued-by-calcom",
    }
    assert result["booking_uid"] != "old-uid"


@pytest.mark.asyncio
async def test_defaults_timezone_to_utc_when_not_configured():
    tool = RescheduleAppointmentTool()

    with patch(
        "backend.tools.reschedule_appointment.reschedule_calendar_booking",
        AsyncMock(return_value={"id": 1, "uid": "u"}),
    ) as mock_reschedule:
        await tool.handler(
            input={"booking_uid": "old-uid", "new_start_time": "2026-08-10T10:00:00"},
            caller_context={"calendar_api_key": "key"},
        )

    assert mock_reschedule.call_args.kwargs["time_zone"] == "UTC"


@pytest.mark.asyncio
async def test_timeout_returns_uncertain_result_not_a_raised_error():
    """This exact case happened on a real call, 2026-08-06 (outliers.md §5): the
    reschedule timed out client-side, Cal.com had genuinely completed it server-side,
    and the model claimed success anyway with nothing confirming it. The handler must
    return an explicit uncertain result instead of letting the model reinterpret a bare
    error however it wants."""
    tool = RescheduleAppointmentTool()

    with patch(
        "backend.tools.reschedule_appointment.reschedule_calendar_booking",
        AsyncMock(side_effect=IntegrationTimeoutError("timed out")),
    ):
        result = await tool.handler(
            input={"booking_uid": "old-uid", "new_start_time": "2026-08-10T10:00:00"},
            caller_context={"calendar_api_key": "key"},
        )

    assert result["status"] == "uncertain"
    assert "reschedule" in result["instruction"]


def test_tool_definition_shape():
    tool = RescheduleAppointmentTool()
    definition = tool.to_definition()

    assert definition["name"] == "reschedule_appointment"
    assert "booking_uid" in definition["input_schema"]["properties"]
    assert "new_start_time" in definition["input_schema"]["properties"]
    assert set(definition["input_schema"]["required"]) == {"booking_uid", "new_start_time"}
