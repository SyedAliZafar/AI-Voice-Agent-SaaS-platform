"""Tests for the check_availability tool handler.

Patches the integration function at the tool module's import site (the existing
test_book_appointment.py convention), so these cover the tool's own wiring —
caller_context -> integration args, and result passthrough — not Cal.com's API shape,
which tests/test_integration_service.py owns.
"""

from unittest.mock import AsyncMock, patch

import pytest

from backend.tools.check_availability import CheckAvailabilityTool


@pytest.mark.asyncio
async def test_passes_caller_context_credentials_through():
    tool = CheckAvailabilityTool()
    mock_check = AsyncMock(return_value={"available": True, "requested_time": "..."})

    with patch("backend.tools.check_availability.check_calendar_availability", mock_check):
        result = await tool.handler(
            input={"start_time": "2026-08-07T09:00:00"},
            caller_context={
                "calendar_id": "6553289",
                "calendar_api_key": "cal_live_x",
                "calendar_timezone": "Europe/Berlin",
            },
        )

    assert result == {"available": True, "requested_time": "..."}
    mock_check.assert_awaited_once_with(
        calendar_id="6553289",
        start_time="2026-08-07T09:00:00",
        api_key="cal_live_x",
        time_zone="Europe/Berlin",
    )


@pytest.mark.asyncio
async def test_timezone_defaults_to_utc_when_not_configured():
    """calendar_timezone comes from the agent's ToolConfig row; an agent that predates it
    must still work rather than KeyError mid-call."""
    tool = CheckAvailabilityTool()
    mock_check = AsyncMock(return_value={"available": False})

    with patch("backend.tools.check_availability.check_calendar_availability", mock_check):
        await tool.handler(
            input={"start_time": "2026-08-07T09:00:00"},
            caller_context={"calendar_id": "1", "calendar_api_key": "k"},
        )

    assert mock_check.await_args.kwargs["time_zone"] == "UTC"


@pytest.mark.asyncio
async def test_unavailable_result_with_alternatives_passes_through_untouched():
    """The alternatives list is what lets the agent offer another time instead of asking
    the caller to guess — the tool must not reshape or drop it."""
    tool = CheckAvailabilityTool()
    payload = {
        "available": False,
        "requested_time": "2026-08-07T10:00:00+02:00",
        "nearby_alternatives": [
            "2026-08-07T10:15:00.000+02:00",
            "2026-08-07T09:45:00.000+02:00",
        ],
    }
    mock_check = AsyncMock(return_value=payload)

    with patch("backend.tools.check_availability.check_calendar_availability", mock_check):
        result = await tool.handler(
            input={"start_time": "2026-08-07T10:00:00"},
            caller_context={"calendar_id": "1", "calendar_api_key": "k"},
        )

    assert result == payload


def test_tool_definition_shape():
    definition = CheckAvailabilityTool().to_definition()

    assert definition["name"] == "check_availability"
    assert definition["input_schema"]["required"] == ["start_time"]
    # No duration_min: Cal.com rejects duration overrides for fixed-length event types,
    # so the schema must not imply a capability that doesn't exist.
    assert "duration_min" not in definition["input_schema"]["properties"]


def test_registered_in_tool_registry():
    """The registry is the only wiring point — a tool that isn't in it is invisible to
    the LLM no matter how correct the class is."""
    from backend.tools import get_tool_definitions, get_tool_handler

    assert any(t["name"] == "check_availability" for t in get_tool_definitions())
    assert get_tool_handler("check_availability") is not None
