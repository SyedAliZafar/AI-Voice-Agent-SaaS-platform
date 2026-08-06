"""Tests for third-party integration request/response shaping (integration_service).

Mocks httpx entirely — these verify the request we build and how we parse the response,
not that Cal.com/HubSpot are reachable. Cal.com's v1 API was removed on 2026-04-08 (a
real test call on 2026-08-05 got "404 Not Found" from POST /v1/bookings), so the booking
path targets v2; these lock in the parts of that contract that are easy to regress.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.services import integration_service


def _mock_client(response_json: dict):
    """Patches httpx.AsyncClient so `async with httpx.AsyncClient() as client` yields a
    mock whose .post/.get returns a response with the given JSON body. (.get is used by
    check_calendar_availability; .post by the booking/CRM writes.)"""
    response = MagicMock()
    response.json.return_value = response_json
    response.raise_for_status = MagicMock()

    client = MagicMock()
    client.post = AsyncMock(return_value=response)
    client.get = AsyncMock(return_value=response)

    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=client)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx, client


class TestBookCalendarSlot:
    @pytest.mark.asyncio
    async def test_posts_v2_shape(self):
        ctx, client = _mock_client({"status": "success", "data": {"id": 123, "uid": "abc"}})

        with patch.object(integration_service.httpx, "AsyncClient", return_value=ctx):
            result = await integration_service.book_calendar_slot(
                calendar_id="6553289",
                start_time="2026-08-05T14:00:00Z",
                duration_min=30,
                attendee_email="caller@example.com",
                api_key="cal_live_xyz",
                attendee_name="Ali",
                time_zone="Europe/Berlin",
            )

        url = client.post.call_args.args[0]
        headers = client.post.call_args.kwargs["headers"]
        body = client.post.call_args.kwargs["json"]

        assert url == "https://api.cal.com/v2/bookings"
        assert headers["Authorization"] == "Bearer cal_live_xyz"
        # Omitting this silently serves an older endpoint revision with a different
        # response envelope — see CAL_API_VERSION.
        assert headers["cal-api-version"] == integration_service.CAL_API_VERSION
        # eventTypeId must be numeric in v2; ToolConfig stores it as a string.
        assert body["eventTypeId"] == 6553289
        assert isinstance(body["eventTypeId"], int)
        # lengthInMinutes must NOT be sent: Cal.com rejects it for any event type that
        # isn't configured with multiple selectable durations (the default), with
        # "Can't specify 'lengthInMinutes' because event type does not have multiple
        # possible lengths". Confirmed live on 2026-08-05.
        assert "lengthInMinutes" not in body
        assert body["attendee"] == {
            "name": "Ali",
            "email": "caller@example.com",
            "timeZone": "Europe/Berlin",
        }
        # Returns the booking object, not the envelope, so callers keep reading ["id"].
        assert result == {"id": 123, "uid": "abc"}

    @pytest.mark.asyncio
    async def test_unwrapped_response_body_is_tolerated(self):
        """A cal-api-version bump that drops the {"status","data"} envelope should degrade
        to "no confirmation id", not raise mid-call."""
        ctx, _ = _mock_client({"id": 456})

        with patch.object(integration_service.httpx, "AsyncClient", return_value=ctx):
            result = await integration_service.book_calendar_slot(
                calendar_id="1",
                start_time="2026-08-05T14:00:00Z",
                duration_min=30,
                attendee_email="c@example.com",
                api_key="k",
            )

        assert result == {"id": 456}


class TestErrorSurfacing:
    """The provider's own message must reach the caller — it becomes the tool result the
    LLM reasons about mid-call AND the CallEvent audit row. A bare status code is useless
    in both places."""

    @pytest.mark.asyncio
    async def test_error_body_is_included_not_just_status(self):
        response = MagicMock()
        response.is_success = False
        response.status_code = 400
        response.text = (
            '{"error":{"message":"Can\'t specify \'lengthInMinutes\' because event type '
            'does not have multiple possible lengths."}}'
        )
        client = MagicMock()
        client.post = AsyncMock(return_value=response)
        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=client)
        ctx.__aexit__ = AsyncMock(return_value=False)

        with patch.object(integration_service.httpx, "AsyncClient", return_value=ctx):
            with pytest.raises(integration_service.IntegrationError) as exc_info:
                await integration_service.book_calendar_slot(
                    calendar_id="1",
                    start_time="2026-08-05T14:00:00Z",
                    duration_min=30,
                    attendee_email="c@example.com",
                    api_key="k",
                )

        message = str(exc_info.value)
        assert "400" in message
        assert "lengthInMinutes" in message

    @pytest.mark.asyncio
    async def test_missing_calendar_key_fails_with_actionable_message(self):
        """An empty key used to build the header "Bearer " and surface as httpx's
        "Illegal header value b'Bearer '" — which names neither the credential nor the
        agent. Seen on every turn of a live call on 2026-08-05."""
        with pytest.raises(integration_service.IntegrationError) as exc_info:
            await integration_service.book_calendar_slot(
                calendar_id="1",
                start_time="2026-08-05T14:00:00Z",
                duration_min=30,
                attendee_email="c@example.com",
                api_key="",
            )

        message = str(exc_info.value)
        assert "calendar_api_key" in message
        assert "Illegal header value" not in message

    @pytest.mark.asyncio
    async def test_missing_crm_key_fails_with_actionable_message(self):
        with pytest.raises(integration_service.IntegrationError) as exc_info:
            await integration_service.create_hubspot_contact(
                email="c@example.com", phone="+1555", notes="n", api_key=""
            )

        assert "crm_api_key" in str(exc_info.value)


class TestToUtcIso:
    def test_naive_datetime_uses_configured_timezone(self):
        """The LLM emits what the caller said out loud ("2pm"), with no offset. Treating
        that as UTC would book the wrong wall-clock time."""
        result = integration_service._to_utc_iso("2026-08-05T14:00:00", "Europe/Berlin")
        # Berlin is UTC+2 in August.
        assert result == "2026-08-05T12:00:00Z"

    def test_aware_datetime_is_respected_not_reinterpreted(self):
        result = integration_service._to_utc_iso("2026-08-05T14:00:00+02:00", "America/New_York")
        assert result == "2026-08-05T12:00:00Z"

    def test_z_suffix_is_parsed_and_preserved(self):
        result = integration_service._to_utc_iso("2026-08-05T14:00:00Z", "Europe/Berlin")
        assert result == "2026-08-05T14:00:00Z"

    def test_utc_default_is_identity(self):
        result = integration_service._to_utc_iso("2026-08-05T14:00:00", "UTC")
        assert result == "2026-08-05T14:00:00Z"
        # Sanity: the parsed instant really is what we think it is.
        assert datetime.fromisoformat(result.replace("Z", "+00:00")) == datetime(
            2026, 8, 5, 14, 0, tzinfo=UTC
        )


class TestLocalDatetime:
    """_local_datetime is shared by _to_utc_iso (booking) and check_calendar_availability
    (slot lookup). If the two ever disagreed about what an ambiguous time means, the
    availability answer would describe a different moment than the booking creates."""

    def test_naive_is_interpreted_in_the_configured_zone(self):
        result = integration_service._local_datetime("2026-08-07T10:00:00", "Europe/Berlin")
        assert result.strftime("%Y-%m-%dT%H:%M") == "2026-08-07T10:00"
        assert result.utcoffset().total_seconds() == 2 * 3600  # Berlin is UTC+2 in August

    def test_aware_is_converted_into_the_configured_zone(self):
        # 08:00Z is 10:00 in Berlin — same instant, expressed locally.
        result = integration_service._local_datetime("2026-08-07T08:00:00Z", "Europe/Berlin")
        assert result.strftime("%Y-%m-%dT%H:%M") == "2026-08-07T10:00"

    def test_agrees_with_to_utc_iso_on_the_same_input(self):
        raw, tz = "2026-08-07T10:00:00", "Europe/Berlin"
        local = integration_service._local_datetime(raw, tz)
        via_utc = datetime.fromisoformat(
            integration_service._to_utc_iso(raw, tz).replace("Z", "+00:00")
        )
        assert local == via_utc


def _slots_payload(day: str, times: list[str], offset: str = "+02:00") -> dict:
    """A realistic /v2/slots body: grouped by local date, each slot a {"start": ...}."""
    return {
        "status": "success",
        "data": {day: [{"start": f"{day}T{t}:00.000{offset}"} for t in times]},
    }


class TestCheckCalendarAvailability:
    @pytest.mark.asyncio
    async def test_requests_the_v2_slots_endpoint_with_its_own_api_version(self):
        ctx, client = _mock_client(_slots_payload("2026-08-07", ["09:00", "09:15"]))

        with patch.object(integration_service.httpx, "AsyncClient", return_value=ctx):
            await integration_service.check_calendar_availability(
                calendar_id="6553289",
                start_time="2026-08-07T09:00:00",
                api_key="cal_live_x",
                time_zone="Europe/Berlin",
            )

        url = client.get.call_args.args[0]
        headers = client.get.call_args.kwargs["headers"]
        params = client.get.call_args.kwargs["params"]

        assert url == "https://api.cal.com/v2/slots"
        assert headers["Authorization"] == "Bearer cal_live_x"
        # Independently versioned from /v2/bookings — must NOT be CAL_API_VERSION.
        assert headers["cal-api-version"] == integration_service.SLOTS_API_VERSION
        assert headers["cal-api-version"] != integration_service.CAL_API_VERSION
        assert params["eventTypeId"] == 6553289
        assert isinstance(params["eventTypeId"], int)
        assert params["start"] == "2026-08-07"
        assert params["end"] == "2026-08-08"
        assert params["timeZone"] == "Europe/Berlin"
        # Fixed-length event types reject a duration override — same reason
        # book_calendar_slot omits lengthInMinutes.
        assert "duration" not in params

    @pytest.mark.asyncio
    async def test_available_when_the_requested_minute_is_in_the_day(self):
        ctx, _ = _mock_client(_slots_payload("2026-08-07", ["09:00", "09:15", "09:30"]))

        with patch.object(integration_service.httpx, "AsyncClient", return_value=ctx):
            result = await integration_service.check_calendar_availability(
                calendar_id="1",
                start_time="2026-08-07T09:15:00",
                api_key="k",
                time_zone="Europe/Berlin",
            )

        assert result["available"] is True
        # Nothing to offer when the requested time itself is free.
        assert "nearby_alternatives" not in result

    @pytest.mark.asyncio
    async def test_unavailable_returns_closest_same_day_alternatives_first(self):
        # 10:00 is absent — the caller's requested time is taken.
        ctx, _ = _mock_client(_slots_payload("2026-08-07", ["09:00", "09:45", "10:15", "14:00"]))

        with patch.object(integration_service.httpx, "AsyncClient", return_value=ctx):
            result = await integration_service.check_calendar_availability(
                calendar_id="1",
                start_time="2026-08-07T10:00:00",
                api_key="k",
                time_zone="Europe/Berlin",
            )

        assert result["available"] is False
        # Closest first: 10:15 and 09:45 are both 15m away (later wins the tie — see
        # _rank), then 09:00 at -60m; 14:00 falls off the cap.
        assert [s[11:16] for s in result["nearby_alternatives"]] == ["10:15", "09:45", "09:00"]
        assert len(result["nearby_alternatives"]) == integration_service._MAX_ALTERNATIVES

    @pytest.mark.asyncio
    async def test_equidistant_tie_prefers_the_later_slot_regardless_of_input_order(self):
        """The tie-break must be ours, not Cal.com's list order — otherwise the answer
        changes if they ever reorder the response."""
        for times in (["09:45", "10:15"], ["10:15", "09:45"]):
            ctx, _ = _mock_client(_slots_payload("2026-08-07", times))
            with patch.object(integration_service.httpx, "AsyncClient", return_value=ctx):
                result = await integration_service.check_calendar_availability(
                    calendar_id="1",
                    start_time="2026-08-07T10:00:00",
                    api_key="k",
                    time_zone="Europe/Berlin",
                )
            assert result["nearby_alternatives"][0][11:16] == "10:15", f"input order {times}"

    @pytest.mark.asyncio
    async def test_fully_booked_day_is_unavailable_with_no_alternatives(self):
        """Cal.com returns data:{} for a day with nothing free — must not KeyError."""
        ctx, _ = _mock_client({"status": "success", "data": {}})

        with patch.object(integration_service.httpx, "AsyncClient", return_value=ctx):
            result = await integration_service.check_calendar_availability(
                calendar_id="1",
                start_time="2026-08-07T10:00:00",
                api_key="k",
                time_zone="Europe/Berlin",
            )

        assert result["available"] is False
        assert result["nearby_alternatives"] == []

    @pytest.mark.asyncio
    async def test_naive_time_is_resolved_in_the_agents_timezone_not_utc(self):
        """The whole point of calendar_timezone: "10am" means 10am where the caller is.
        Asking UTC for the Berlin day would query the wrong local date near midnight."""
        ctx, client = _mock_client(_slots_payload("2026-08-07", ["10:00"]))

        with patch.object(integration_service.httpx, "AsyncClient", return_value=ctx):
            result = await integration_service.check_calendar_availability(
                calendar_id="1",
                start_time="2026-08-07T10:00:00",
                api_key="k",
                time_zone="Europe/Berlin",
            )

        assert client.get.call_args.kwargs["params"]["start"] == "2026-08-07"
        assert result["available"] is True
        assert result["requested_time"].startswith("2026-08-07T10:00:00+02:00")

    @pytest.mark.asyncio
    async def test_missing_calendar_key_fails_before_any_request(self):
        with pytest.raises(integration_service.IntegrationError) as exc_info:
            await integration_service.check_calendar_availability(
                calendar_id="1", start_time="2026-08-07T10:00:00", api_key=""
            )
        message = str(exc_info.value)
        assert "calendar_api_key" in message
        assert "check_availability" in message

    @pytest.mark.asyncio
    async def test_missing_calendar_id_fails_before_any_request(self):
        with pytest.raises(integration_service.IntegrationError) as exc_info:
            await integration_service.check_calendar_availability(
                calendar_id="", start_time="2026-08-07T10:00:00", api_key="k"
            )
        assert "calendar_id" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_http_error_surfaces_calcom_message(self):
        response = MagicMock()
        response.is_success = False
        response.status_code = 400
        response.text = '{"error":{"message":"Invalid eventTypeId"}}'
        client = MagicMock()
        client.get = AsyncMock(return_value=response)
        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=client)
        ctx.__aexit__ = AsyncMock(return_value=False)

        with patch.object(integration_service.httpx, "AsyncClient", return_value=ctx):
            with pytest.raises(integration_service.IntegrationError) as exc_info:
                await integration_service.check_calendar_availability(
                    calendar_id="1", start_time="2026-08-07T10:00:00", api_key="k"
                )

        assert "Invalid eventTypeId" in str(exc_info.value)
