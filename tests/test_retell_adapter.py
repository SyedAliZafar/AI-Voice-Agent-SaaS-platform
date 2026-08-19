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
