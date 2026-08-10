"""Tests for public_url — the PUBLIC_BASE_URL=auto tunnel-hostname resolver.

The behavior that matters operationally: an explicit URL is never second-guessed (named
tunnel / production / every other test in this suite), and "auto" discovers the quick
tunnel's current hostname so a tunnel restart stops being a manual .env edit.
"""

import httpx
import pytest

from backend.services import public_url


@pytest.fixture(autouse=True)
def _reset_cache():
    """The resolver memoizes across calls by design — that must not leak between tests."""
    public_url.reset_cache()
    yield
    public_url.reset_cache()


def _transport(handler):
    """An httpx.AsyncClient that answers from `handler` instead of the network."""
    return httpx.MockTransport(handler)


@pytest.fixture
def mock_metrics(monkeypatch):
    """Point the resolver's httpx client at a fake cloudflared metrics server."""

    def _install(handler):
        real_client = httpx.AsyncClient

        def _factory(*args, **kwargs):
            kwargs["transport"] = _transport(handler)
            return real_client(*args, **kwargs)

        monkeypatch.setattr(public_url.httpx, "AsyncClient", _factory)

    return _install


class TestExplicitUrlWins:
    @pytest.mark.asyncio
    async def test_literal_url_is_returned_untouched(self, monkeypatch):
        monkeypatch.setattr(
            public_url.settings, "public_base_url", "https://voiceagent.example.com"
        )
        assert await public_url.get_public_base_url() == "https://voiceagent.example.com"
        assert public_url.is_auto() is False

    @pytest.mark.asyncio
    async def test_trailing_slash_is_stripped(self, monkeypatch):
        monkeypatch.setattr(public_url.settings, "public_base_url", "https://example.com/")
        assert await public_url.get_public_base_url() == "https://example.com"

    @pytest.mark.asyncio
    async def test_unset_returns_empty_not_an_error(self, monkeypatch):
        """The hosted-LLM path is designed to work with no tunnel at all — an unset
        value must stay a benign empty string, not become a discovery failure."""
        monkeypatch.setattr(public_url.settings, "public_base_url", "")
        assert await public_url.get_public_base_url() == ""


class TestAutoDiscovery:
    @pytest.mark.asyncio
    async def test_auto_discovers_hostname_from_cloudflared(self, monkeypatch, mock_metrics):
        monkeypatch.setattr(public_url.settings, "public_base_url", "auto")
        mock_metrics(
            lambda req: httpx.Response(200, json={"hostname": "abc-def.trycloudflare.com"})
        )
        assert await public_url.get_public_base_url() == "https://abc-def.trycloudflare.com"
        assert public_url.is_auto() is True

    @pytest.mark.asyncio
    async def test_auto_is_case_and_whitespace_tolerant(self, monkeypatch, mock_metrics):
        monkeypatch.setattr(public_url.settings, "public_base_url", "  AUTO  ")
        mock_metrics(lambda req: httpx.Response(200, json={"hostname": "x.trycloudflare.com"}))
        assert await public_url.get_public_base_url() == "https://x.trycloudflare.com"

    @pytest.mark.asyncio
    async def test_result_is_cached_not_refetched(self, monkeypatch, mock_metrics):
        monkeypatch.setattr(public_url.settings, "public_base_url", "auto")
        calls = {"n": 0}

        def handler(request):
            calls["n"] += 1
            return httpx.Response(200, json={"hostname": f"host{calls['n']}.trycloudflare.com"})

        mock_metrics(handler)
        first = await public_url.get_public_base_url()
        second = await public_url.get_public_base_url()
        assert first == second == "https://host1.trycloudflare.com"
        assert calls["n"] == 1

    @pytest.mark.asyncio
    async def test_force_refresh_repicks_after_a_tunnel_restart(self, monkeypatch, mock_metrics):
        """The self-heal path: the tunnel restarted and now has a different hostname."""
        monkeypatch.setattr(public_url.settings, "public_base_url", "auto")
        calls = {"n": 0}

        def handler(request):
            calls["n"] += 1
            return httpx.Response(200, json={"hostname": f"host{calls['n']}.trycloudflare.com"})

        mock_metrics(handler)
        assert await public_url.get_public_base_url() == "https://host1.trycloudflare.com"
        refreshed = await public_url.get_public_base_url(force_refresh=True)
        assert refreshed == "https://host2.trycloudflare.com"
        assert calls["n"] == 2


class TestDiscoveryFailures:
    @pytest.mark.asyncio
    async def test_unreachable_metrics_raises_actionable_error(self, monkeypatch, mock_metrics):
        monkeypatch.setattr(public_url.settings, "public_base_url", "auto")

        def handler(request):
            raise httpx.ConnectError("connection refused", request=request)

        mock_metrics(handler)
        with pytest.raises(public_url.PublicUrlUnavailable) as exc:
            await public_url.get_public_base_url()
        # Must tell the operator what to actually do, not just what failed.
        assert "tunnel-quick" in str(exc.value)

    @pytest.mark.asyncio
    async def test_missing_hostname_field_explains_named_tunnel_case(
        self, monkeypatch, mock_metrics
    ):
        """/quicktunnel only exists for quick tunnels — a named tunnel answers without
        a hostname, and the error should say to set the URL literally."""
        monkeypatch.setattr(public_url.settings, "public_base_url", "auto")
        mock_metrics(lambda req: httpx.Response(200, json={}))
        with pytest.raises(public_url.PublicUrlUnavailable, match="named tunnel"):
            await public_url.get_public_base_url()

    @pytest.mark.asyncio
    async def test_http_error_status_raises(self, monkeypatch, mock_metrics):
        monkeypatch.setattr(public_url.settings, "public_base_url", "auto")
        mock_metrics(lambda req: httpx.Response(404))
        with pytest.raises(public_url.PublicUrlUnavailable):
            await public_url.get_public_base_url()
