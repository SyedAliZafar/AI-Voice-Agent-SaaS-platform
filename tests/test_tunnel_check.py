"""Tests for backend/services/tunnel_check.py — the reachability probe shared by
test_call_service's custom-LLM preflight and scripts/check_custom_llm.py.

Uses httpx.MockTransport rather than a real network call, since the whole point of this
module is to detect the case where a request goes nowhere (DNS failure, dead tunnel).
"""

import httpx
import pytest

from backend.services import tunnel_check


@pytest.mark.asyncio
async def test_check_public_url_reachable_empty_url():
    reason = await tunnel_check.check_public_url_reachable("")
    assert reason == "PUBLIC_BASE_URL is empty"


@pytest.mark.asyncio
async def test_check_public_url_reachable_ok(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://good-tunnel.example.com/health"
        return httpx.Response(200, json={"status": "ok"})

    _patch_async_client(monkeypatch, handler)

    reason = await tunnel_check.check_public_url_reachable("https://good-tunnel.example.com")
    assert reason is None


@pytest.mark.asyncio
async def test_check_public_url_reachable_strips_trailing_slash(monkeypatch):
    seen_urls = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_urls.append(str(request.url))
        return httpx.Response(200)

    _patch_async_client(monkeypatch, handler)

    await tunnel_check.check_public_url_reachable("https://good-tunnel.example.com/")
    assert seen_urls == ["https://good-tunnel.example.com/health"]


@pytest.mark.asyncio
async def test_check_public_url_reachable_non_200(monkeypatch):
    _patch_async_client(monkeypatch, lambda request: httpx.Response(502))

    reason = await tunnel_check.check_public_url_reachable("https://flaky.example.com")
    assert reason is not None
    assert "502" in reason


@pytest.mark.asyncio
async def test_check_public_url_reachable_connect_error(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Name or service not known", request=request)

    _patch_async_client(monkeypatch, handler)

    reason = await tunnel_check.check_public_url_reachable("https://dead-tunnel.example.com")
    assert reason is not None
    assert "cannot connect" in reason


@pytest.mark.asyncio
async def test_check_public_url_reachable_timeout(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timed out", request=request)

    _patch_async_client(monkeypatch, handler)

    reason = await tunnel_check.check_public_url_reachable("https://slow-tunnel.example.com")
    assert reason is not None


def _patch_async_client(monkeypatch, handler) -> None:
    """Swap httpx.AsyncClient for one whose transport is a MockTransport, so
    tunnel_check's real `async with httpx.AsyncClient(...)` call exercises the module
    under test unmodified while never touching the network.
    """
    real_client_cls = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client_cls(*args, **kwargs)

    monkeypatch.setattr(tunnel_check.httpx, "AsyncClient", factory)
