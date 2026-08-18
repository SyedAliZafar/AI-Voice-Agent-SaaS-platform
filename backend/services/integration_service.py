"""Third-party integrations: CRM sync, calendar booking, custom webhooks.

Keep each integration's API quirks isolated in its own function — tools/
call into these rather than making raw HTTP calls themselves.

Errors here surface the provider's own message, not just the status code (see
_raise_for_status_with_body). That text goes straight back to the LLM as the tool result
(llm_service._execute_tool_calls) and into the CallEvent(event_type="tool_call") audit
row, so it's both what the agent reasons about mid-call and what you debug from
afterwards. A bare "400 Bad Request" is useless in both places — it cost a live test call
on 2026-08-05 to discover that Cal.com was actually saying "remove the 'lengthInMinutes'
field".
"""

from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import httpx

# Cal.com pins endpoint behavior to a date-versioned header rather than the URL — omitting
# it silently serves an older revision of the endpoint with a different response shape, so
# it's mandatory here, not optional. Bump deliberately and re-check the response parsing in
# book_calendar_slot when you do. Verified against a real booking on 2026-08-05.
CAL_API_VERSION = "2026-02-25"

# Each Cal.com v2 sub-resource is versioned independently — /v2/slots is NOT on the same
# date as /v2/bookings above. Deliberate, not a typo: verified 2026-08-06 by a live GET
# against the real event type, which correctly excluded already-booked times and included
# genuinely free ones. Do not "tidy" these two into one constant.
SLOTS_API_VERSION = "2024-09-04"

# How many same-day alternatives check_calendar_availability offers back when the
# requested time is taken. Three is enough for the agent to make a spoken suggestion
# without reading a list at the caller.
_MAX_ALTERNATIVES = 3

# Shared by every Cal.com-mutating call (book/cancel/reschedule) so the timeout value in
# an IntegrationTimeoutError's message can never drift from the client's actual timeout.
_CALCOM_TIMEOUT_SECONDS = 20.0


class IntegrationError(Exception):
    """A third-party API rejected the request, or it isn't configured. Carries the
    provider's own error text so the LLM can react to it (e.g. offer another time when a
    slot is taken) instead of guessing from a status code."""


class IntegrationTimeoutError(IntegrationError):
    """The request timed out waiting for a response — NOT a confirmed failure.

    A live call on 2026-08-06 (outliers.md §5) confirmed exactly why this distinction
    matters: a reschedule_appointment dispatch timed out client-side after
    _CALCOM_TIMEOUT_SECONDS with no response, our code reported a bare error, and the
    model told the caller it succeeded anyway — which happened to be true (Cal.com had
    processed the request and moved the booking before our client gave up waiting for
    the response), but only by luck. The same timeout on a request that genuinely failed
    server-side would produce an identical, equally confident, false claim.

    Callers (backend/tools/base.py's uncertain_result) must not treat this the same as a
    definite rejection (a 400/404, which raises plain IntegrationError) — the request may
    have been received and processed by Cal.com even though we never saw the response.
    """


def _raise_for_status_with_body(resp: httpx.Response, provider: str) -> None:
    """httpx's own raise_for_status() drops the response body, which is where every API
    puts the actual reason. Re-raise with it included, truncated so a huge HTML error page
    can't blow up the prompt we feed back to the LLM."""
    if resp.is_success:
        return
    detail = resp.text[:500] if resp.text else "(empty response body)"
    raise IntegrationError(f"{provider} returned HTTP {resp.status_code}: {detail}")


def _require(value: str, name: str, tool_hint: str) -> str:
    """Fail with an actionable message when a credential is missing.

    Without this, an empty api_key builds the header "Bearer " and httpx raises
    "Illegal header value b'Bearer '" — which tells a caller nothing about which agent is
    misconfigured. Seen live on 2026-08-05: create_lead failed this way on every turn
    because the agent had no create_lead ToolConfig row.
    """
    if not value:
        raise IntegrationError(
            f"{name} is not configured for this agent — add it to the agent's "
            f"{tool_hint} ToolConfig row (see scripts/seed_booking_tool_config.py)."
        )
    return value


async def create_hubspot_contact(email: str, phone: str, notes: str, api_key: str) -> dict:
    _require(api_key, "crm_api_key", "create_lead")
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.post(
            "https://api.hubapi.com/crm/v3/objects/contacts",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"properties": {"email": email, "phone": phone, "notes": notes}},
        )
        _raise_for_status_with_body(resp, "HubSpot")
        return resp.json()


async def verify_hubspot_credentials(api_key: str) -> None:
    """Is this HubSpot token usable? Raises IntegrationError with the provider's own text
    if not; returns None on success.

    Backs POST /api/integrations/{kind}/test, so an operator finds out their token is
    wrong while they're on the settings page rather than from a silently failing CRM sync
    three days later.

    A one-record read of the object we actually write to, deliberately: a token can be
    valid and still lack the `crm.objects.contacts.*` scopes a private app has to grant
    explicitly, and asking for the wrong thing would report healthy right up until the
    first real write. Read-only, so it can be run as often as anyone likes and never
    creates anything.

    Timeouts are NOT translated to IntegrationTimeoutError here. That distinction exists
    because a mutating request may have landed despite the timeout (see the class
    docstring); nothing about a failed GET is ambiguous — retrying it is free.
    """
    _require(api_key, "api_key", "crm")
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(
            "https://api.hubapi.com/crm/v3/objects/contacts",
            headers={"Authorization": f"Bearer {api_key}"},
            params={"limit": 1},
        )
        _raise_for_status_with_body(resp, "HubSpot")


def _local_datetime(start_time: str, time_zone: str) -> datetime:
    """Resolve an LLM-supplied start time to an aware datetime in `time_zone`.

    The LLM routinely emits a naive local datetime ("2026-08-05T14:00:00") because that's
    how the caller said it out loud, so a naive value is interpreted in `time_zone` (the
    agent's configured calendar timezone) rather than silently assumed to be UTC —
    assuming UTC would book the caller at the wrong wall-clock time, which is worse than
    failing. Already-aware values are respected and just converted.

    Shared by _to_utc_iso (which needs the UTC instant for a booking) and
    check_calendar_availability (which needs the caller's local calendar day and
    wall-clock time, since Cal.com's slots response is keyed by local date in the
    requested timeZone). Both must interpret an ambiguous time identically, or the
    availability check would answer about a different moment than the booking creates.
    """
    parsed = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo(time_zone))
    return parsed.astimezone(ZoneInfo(time_zone))


def _to_utc_iso(start_time: str, time_zone: str) -> str:
    """Cal.com v2 wants an ISO-8601 instant — see _local_datetime for how a naive input
    is resolved."""
    return _local_datetime(start_time, time_zone).astimezone(UTC).isoformat().replace("+00:00", "Z")


async def book_calendar_slot(
    calendar_id: str,
    start_time: str,
    duration_min: int,
    attendee_email: str,
    api_key: str,
    attendee_name: str = "Caller",
    time_zone: str = "UTC",
) -> dict[str, Any]:
    """Books via Cal.com's v2 API. Swap for Google Calendar API as needed.

    v2, not v1: Cal.com removed every v1 endpoint on 2026-04-08, so the old
    POST /v1/bookings this used to call now 404s for everyone regardless of credentials.

    duration_min is deliberately NOT sent. Cal.com derives the length from the event type,
    and rejects the request outright ("Can't specify 'lengthInMinutes' because event type
    does not have multiple possible lengths") for any event type that isn't explicitly
    configured with several selectable durations — which is the default. The parameter is
    kept in the signature because the caller (and the LLM's tool schema) still reasons in
    terms of a requested duration; the event type is simply the authority on it.

    Returns the booking object itself (the `data` envelope member), not the raw response
    body, so callers keep reading `result["id"]` the way they did under v1.
    """
    _require(api_key, "calendar_api_key", "book_appointment")
    _require(calendar_id, "calendar_id", "book_appointment")
    async with httpx.AsyncClient(timeout=_CALCOM_TIMEOUT_SECONDS) as client:
        try:
            resp = await client.post(
                "https://api.cal.com/v2/bookings",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "cal-api-version": CAL_API_VERSION,
                    "Content-Type": "application/json",
                },
                json={
                    # eventTypeId is numeric in v2; ToolConfig.config stores it as a string.
                    "eventTypeId": int(calendar_id),
                    "start": _to_utc_iso(start_time, time_zone),
                    "attendee": {
                        "name": attendee_name,
                        "email": attendee_email,
                        "timeZone": time_zone,
                    },
                },
            )
        except httpx.TimeoutException as exc:
            raise IntegrationTimeoutError(
                f"Cal.com did not respond within {_CALCOM_TIMEOUT_SECONDS}s to a booking "
                f"request — it may have been created anyway; this is not a confirmed failure."
            ) from exc
        _raise_for_status_with_body(resp, "Cal.com")
        payload = resp.json()
        # Successful v2 responses wrap the booking as {"status": "success", "data": {...}}.
        # Tolerate an unwrapped body so a cal-api-version bump that changes the envelope
        # degrades to "no confirmation id" rather than a KeyError mid-call.
        return payload.get("data", payload) if isinstance(payload, dict) else payload


async def check_calendar_availability(
    calendar_id: str,
    start_time: str,
    api_key: str,
    time_zone: str = "UTC",
) -> dict[str, Any]:
    """Is `start_time` actually free? Read-only — never creates anything.

    Exists because book_appointment used to be the only availability signal in the whole
    system, which left the agent structurally unable to answer "is 2pm free?" without
    attempting a write. On a real call (outliers.md §3) it resolved that by guessing, and
    happened to guess right — a fabrication that lands looks exactly like the system
    working, which is why this had to become a real capability rather than a prompt rule.

    Cal.com has no "is this one instant free" endpoint — only "list slots in a range" —
    so this asks for the requested local day and checks whether the requested minute is
    among the returned slots. The response is keyed by local calendar date in the
    requested timeZone, hence _local_datetime rather than a UTC instant.

    duration is deliberately NOT sent, for the same reason book_calendar_slot omits
    lengthInMinutes: the event type is the authority on its own length, and Cal.com
    rejects duration overrides for fixed-length event types.
    """
    _require(api_key, "calendar_api_key", "check_availability")
    _require(calendar_id, "calendar_id", "check_availability")

    requested = _local_datetime(start_time, time_zone)
    day = requested.strftime("%Y-%m-%d")
    # Compare to the minute: Cal.com returns full offsets ("2026-08-07T09:00:00.000+02:00")
    # whose seconds/millis/offset formatting we don't want to depend on.
    requested_key = requested.strftime("%Y-%m-%dT%H:%M")

    async with httpx.AsyncClient(timeout=_CALCOM_TIMEOUT_SECONDS) as client:
        resp = await client.get(
            "https://api.cal.com/v2/slots",
            headers={
                "Authorization": f"Bearer {api_key}",
                "cal-api-version": SLOTS_API_VERSION,
            },
            params={
                "eventTypeId": int(calendar_id),
                "start": day,
                # `end` is exclusive of nothing in particular — asking for the next day
                # is simply the smallest range that reliably contains `day`.
                "end": (requested + timedelta(days=1)).strftime("%Y-%m-%d"),
                "timeZone": time_zone,
            },
        )
        _raise_for_status_with_body(resp, "Cal.com")
        payload = resp.json()

    data = payload.get("data", {}) if isinstance(payload, dict) else {}
    day_slots = data.get(day, []) if isinstance(data, dict) else []
    slot_starts = [s.get("start", "") for s in day_slots if isinstance(s, dict)]

    available = any(start[:16] == requested_key for start in slot_starts)
    result: dict[str, Any] = {
        "available": available,
        "requested_time": requested.isoformat(),
    }

    if not available:
        # Hand back same-day alternatives, closest first, so the agent can offer one
        # instead of making the caller guess again. Same-day only — a multi-day search
        # is a different feature and would slow the turn down for little gain.
        def _rank(start: str) -> tuple[float, int]:
            delta = (datetime.fromisoformat(start) - requested).total_seconds()
            # Ties (e.g. 09:45 and 10:15 against a 10:00 request) resolve to the LATER
            # slot: a caller who can't have 10:00 is usually still free at 10:15, but may
            # not have been free at 09:45 — and relying on Cal.com's own list order to
            # break the tie would make our answer depend on theirs.
            return (abs(delta), 0 if delta > 0 else 1)

        result["nearby_alternatives"] = sorted((s for s in slot_starts if s), key=_rank)[
            :_MAX_ALTERNATIVES
        ]

    return result


async def cancel_calendar_booking(
    booking_uid: str,
    api_key: str,
    reason: str | None = None,
) -> dict[str, Any]:
    """Cancels a booking via Cal.com's v2 API — outliers.md §5.

    booking_uid, not the numeric id: cancel and reschedule both key on Cal.com's string
    `uid` in the URL path, confirmed against the real API (`POST
    /v2/bookings/{bookingUid}/cancel`, verified 2026-08-06 by actually cancelling a real
    leftover test booking rather than trusting docs alone — response envelope, `data.id`/
    `data.uid`, and `data.status == "cancelled"` all matched the documented shape exactly).
    Same cal-api-version as book_calendar_slot (2026-02-25, confirmed on two independent
    doc fetches) — NOT check_calendar_availability's SLOTS_API_VERSION.

    Returns the booking object itself (the `data` envelope member), same convention as
    book_calendar_slot/check_calendar_availability — callers read `result["status"]`.

    reason is NOT actually optional against the real API, despite Cal.com's own v2 docs
    describing cancellationReason as optional. Confirmed live on 2026-08-06: a real call
    let the caller cancel with no reason given, this sent an empty body as the docs
    implied was fine, and Cal.com rejected it with "Cancellation reason is required".
    Falls back to a generic reason rather than failing the whole cancellation over
    something this minor.
    """
    _require(api_key, "calendar_api_key", "cancel_appointment")
    _require(booking_uid, "booking_uid", "cancel_appointment")
    async with httpx.AsyncClient(timeout=_CALCOM_TIMEOUT_SECONDS) as client:
        try:
            resp = await client.post(
                f"https://api.cal.com/v2/bookings/{booking_uid}/cancel",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "cal-api-version": CAL_API_VERSION,
                    "Content-Type": "application/json",
                },
                json={"cancellationReason": reason or "Cancelled by caller"},
            )
        except httpx.TimeoutException as exc:
            raise IntegrationTimeoutError(
                f"Cal.com did not respond within {_CALCOM_TIMEOUT_SECONDS}s to a cancel "
                f"request — it may have been cancelled anyway; this is not a confirmed failure."
            ) from exc
        _raise_for_status_with_body(resp, "Cal.com")
        payload = resp.json()
        return payload.get("data", payload) if isinstance(payload, dict) else payload


async def reschedule_calendar_booking(
    booking_uid: str,
    new_start_time: str,
    api_key: str,
    time_zone: str = "UTC",
) -> dict[str, Any]:
    """Moves a booking to a new time via Cal.com's v2 API — outliers.md §5.

    One atomic call (`POST /v2/bookings/{bookingUid}/reschedule`) — no separate
    cancel-then-create orchestration on our side, so no client-side race where a
    cancellation could succeed while the rebooking fails and the caller loses the
    appointment entirely.

    booking_uid IN THE RETURNED RESULT IS A NEW VALUE, NOT THE ONE PASSED IN. Confirmed
    empirically 2026-08-06 (not assumed from docs, which read ambiguously — "the booking
    is moved" could imply an in-place mutation): a real reschedule probe showed the
    response's `data.uid` genuinely differs from the `booking_uid` argument — Cal.com
    auto-cancels the original and issues a new booking (carrying `rescheduledFromUid`
    pointing back to the old one) in the same call. Callers of this function MUST treat
    the returned `uid` as the appointment's current identifier for anything that acts on
    it afterward (retell_ws.py's ledger does this — see reschedule_appointment.py).

    duration_min is not a parameter here: rescheduling doesn't change an event type's
    length, only its start time.
    """
    _require(api_key, "calendar_api_key", "reschedule_appointment")
    _require(booking_uid, "booking_uid", "reschedule_appointment")
    async with httpx.AsyncClient(timeout=_CALCOM_TIMEOUT_SECONDS) as client:
        try:
            resp = await client.post(
                f"https://api.cal.com/v2/bookings/{booking_uid}/reschedule",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "cal-api-version": CAL_API_VERSION,
                    "Content-Type": "application/json",
                },
                json={"start": _to_utc_iso(new_start_time, time_zone)},
            )
        except httpx.TimeoutException as exc:
            # This exact case happened live on 2026-08-06 (outliers.md §5): the request
            # timed out here, and Cal.com had genuinely completed the reschedule before
            # our client gave up waiting. See IntegrationTimeoutError's docstring.
            raise IntegrationTimeoutError(
                f"Cal.com did not respond within {_CALCOM_TIMEOUT_SECONDS}s to a "
                f"reschedule request — it may have completed anyway; this is not a "
                f"confirmed failure."
            ) from exc
        _raise_for_status_with_body(resp, "Cal.com")
        payload = resp.json()
        return payload.get("data", payload) if isinstance(payload, dict) else payload
