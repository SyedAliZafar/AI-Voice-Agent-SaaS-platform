"""Tests for RetellAdapter's emergency-stop surface.

The status codes asserted here were verified against the live Retell API — an
already-ended call answers 400 with "Can only stop an ongoing call.", an unknown id
answers 404. Both must read as success, since "the call is not up" is what the caller
asked for. Getting this wrong is not cosmetic: hanging up inherently races the call
ending by itself, so a too-strict adapter reports failure for calls that are down.
"""

import httpx
import pytest

from backend.services.retell_adapter import RetellAdapter


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "body"),
    [
        (400, '{"status":"error","message":"Can only stop an ongoing call."}'),
        (404, '{"status":"error","message":"Not Found"}'),
    ],
)
async def test_stop_call_treats_already_over_as_success(monkeypatch, status, body):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, text=body)

    _patch_transport(monkeypatch, handler)
    await RetellAdapter().stop_call("call_x")  # must not raise


@pytest.mark.asyncio
async def test_stop_call_raises_on_a_genuine_bad_request(monkeypatch):
    """Only the 'already ongoing' 400 is benign — a malformed request must still surface,
    or a broken call to this endpoint would look like a successful hangup forever."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text='{"status":"error","message":"Invalid api key"}')

    _patch_transport(monkeypatch, handler)
    with pytest.raises(httpx.HTTPStatusError):
        await RetellAdapter().stop_call("call_x")


@pytest.mark.asyncio
async def test_stop_call_raises_on_server_error(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    _patch_transport(monkeypatch, handler)
    with pytest.raises(httpx.HTTPStatusError):
        await RetellAdapter().stop_call("call_x")


@pytest.mark.asyncio
async def test_list_live_calls_sends_the_array_filter_shape(monkeypatch):
    """Regression guard: the bundled SDK's types describe a {op,type,value} filter object
    that the deployed REST API rejects with 'call_status must be array'. Verified against
    the live endpoint — if someone 'fixes' the adapter to match the SDK, this fails."""
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        seen.update(json.loads(request.content))
        return httpx.Response(200, json=[{"call_id": "call_1", "call_status": "ongoing"}])

    _patch_transport(monkeypatch, handler)
    calls = await RetellAdapter().list_live_calls()

    assert seen["filter_criteria"] == {"call_status": ["ongoing"]}
    assert [c["call_id"] for c in calls] == ["call_1"]


@pytest.mark.asyncio
async def test_list_live_calls_accepts_a_paginated_body(monkeypatch):
    """Retell returns a bare array today; the SDK models {items: [...]}. Accept both so a
    pagination rollout can't silently turn 'kill everything live' into a no-op."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"items": [{"call_id": "call_2"}], "has_more": False})

    _patch_transport(monkeypatch, handler)
    calls = await RetellAdapter().list_live_calls()

    assert [c["call_id"] for c in calls] == ["call_2"]


# --- Platform agent roster (ADR-012) ------------------------------------------


@pytest.mark.asyncio
async def test_list_platform_agents_keeps_only_the_latest_version(monkeypatch):
    """Retell's list-agents returns one entry per agent VERSION. Showing every one would
    fill the dial picker with duplicates, and dialing a non-latest version isn't even
    what override_agent_id does — it dials the latest."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[
                {
                    "agent_id": "agent_1",
                    "agent_name": "Roofing v1",
                    "version": 1,
                    "voice_id": "11labs-Marissa",
                    "response_engine": {"type": "retell-llm", "llm_id": "llm_1"},
                },
                {
                    "agent_id": "agent_1",
                    "agent_name": "Roofing v3",
                    "version": 3,
                    "voice_id": "11labs-Marissa",
                    "response_engine": {"type": "retell-llm", "llm_id": "llm_1"},
                },
                {
                    "agent_id": "agent_2",
                    "agent_name": "HVAC",
                    "version": 0,
                    "response_engine": {"type": "custom-llm"},
                },
            ],
        )

    _patch_transport(monkeypatch, handler)
    agents = await RetellAdapter().list_platform_agents()

    by_id = {a["external_id"]: a for a in agents}
    assert set(by_id) == {"agent_1", "agent_2"}
    assert by_id["agent_1"]["name"] == "Roofing v3"
    assert by_id["agent_1"]["engine"] == "retell-llm"
    # version 0 is a real version, not "unset" — it must not be dropped as falsy.
    assert by_id["agent_2"]["engine"] == "custom-llm"
    assert by_id["agent_2"]["voice_id"] is None


@pytest.mark.asyncio
async def test_list_platform_agents_accepts_a_paginated_body(monkeypatch):
    """Same defensive shape as list_live_calls: a Retell-side pagination rollout must not
    silently empty the dial picker."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"items": [{"agent_id": "agent_1"}], "has_more": False})

    _patch_transport(monkeypatch, handler)
    agents = await RetellAdapter().list_platform_agents()

    # An unnamed agent falls back to its id — a blank row is indistinguishable from the
    # next blank row in a picker.
    assert agents == [
        {
            "external_id": "agent_1",
            "name": "agent_1",
            "voice_id": None,
            "engine": None,
            "version": None,
            "last_modified_ms": None,
        }
    ]


# --- dynamic variables (ADR-012) ----------------------------------------------


@pytest.mark.asyncio
async def test_get_agent_dynamic_variables_scans_prompt_and_begin_message(monkeypatch):
    """Retell has no endpoint reporting an agent's placeholders — its own dashboard
    derives them by scanning the prompt, and so do we. Verified against a real agent:
    the four names the dashboard offered are exactly what this finds."""

    def handler(request: httpx.Request) -> httpx.Response:
        if "get-agent" in str(request.url):
            return httpx.Response(
                200,
                json={
                    "agent_id": "agent_1",
                    "response_engine": {"type": "retell-llm", "llm_id": "llm_1"},
                },
            )
        return httpx.Response(
            200,
            json={
                "llm_id": "llm_1",
                "general_prompt": (
                    "You are calling {{company_name}} about {{ current_time }}. "
                    "Mention {{company_name}} again."
                ),
                "begin_message": "Hi {{contact_name}}!",
            },
        )

    _patch_transport(monkeypatch, handler)
    variables = await RetellAdapter().get_agent_dynamic_variables("agent_1")

    # Deduped, sorted, whitespace inside the braces tolerated, and begin_message
    # included — an opener is exactly where an unfilled placeholder is spoken first.
    assert variables == ["company_name", "contact_name", "current_time"]


@pytest.mark.asyncio
async def test_get_agent_dynamic_variables_is_empty_when_there_is_no_prompt_to_scan(
    monkeypatch,
):
    """A custom-llm agent keeps its prompt on whatever server answers the websocket.
    Returning [] (not raising) keeps "we can't inspect it" from blocking a dial."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"agent_id": "agent_1", "response_engine": {"type": "custom-llm"}},
        )

    _patch_transport(monkeypatch, handler)
    assert await RetellAdapter().get_agent_dynamic_variables("agent_1") == []


@pytest.mark.asyncio
async def test_create_outbound_call_omits_empty_dynamic_variables(monkeypatch):
    """The local-agent paths never use this; an empty object would be a pointless
    difference in their request bodies."""
    bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        import json as _json

        bodies.append(_json.loads(request.content))
        return httpx.Response(200, json={"call_id": "call_1"})

    _patch_transport(monkeypatch, handler)

    await RetellAdapter().create_outbound_call("+1", "+2", "agent_1")
    assert "retell_llm_dynamic_variables" not in bodies[-1]

    await RetellAdapter().create_outbound_call(
        "+1", "+2", "agent_1", dynamic_variables={"company_name": "Acme"}
    )
    assert bodies[-1]["retell_llm_dynamic_variables"] == {"company_name": "Acme"}


def _patch_transport(monkeypatch, handler) -> None:
    """Route the adapter's httpx.AsyncClient through a MockTransport.

    Patched at backend.services.retell_adapter.httpx.AsyncClient rather than globally so
    only the adapter's own requests are intercepted.
    """
    import backend.services.retell_adapter as mod

    real_client = httpx.AsyncClient

    def _factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(*args, **kwargs)

    monkeypatch.setattr(mod.httpx, "AsyncClient", _factory)
