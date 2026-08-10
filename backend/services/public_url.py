"""What is our public base URL right now?

`PUBLIC_BASE_URL` used to be a plain string every caller read straight off `settings`.
That works for a named tunnel or a real deployment, where the hostname is fixed — but
the zero-setup cloudflared *quick* tunnel mints a brand-new
`https://<random>.trycloudflare.com` host on every single start, so the value in `.env`
goes stale the moment the tunnel restarts. That has cost real, billed test calls four
times (2026-08-04, -08-05, -08-08, -08-10) and each recovery was the same manual ritual:
read the URL out of `docker compose logs`, paste it into `.env`, recreate the API
container because `docker compose restart` doesn't re-read `.env`.

So `PUBLIC_BASE_URL` now accepts the sentinel `auto`, which means "ask cloudflared".
cloudflared's metrics server exposes the assigned hostname at `/quicktunnel`:

    GET http://tunnel-quick:20241/quicktunnel
    -> {"hostname": "solutions-obituaries-sequences-britney.trycloudflare.com"}

(Verified empirically against `cloudflare/cloudflared:latest` on 2026-08-10 before this
module was written — this repo has been burned enough times assuming a third-party
contract from docs alone; see phases/in-progress/session5.md.)

An explicit URL always wins, so the named tunnel, production, and every existing test
that sets a concrete `public_base_url` are completely unaffected by this file.
"""

import asyncio

import httpx

from backend.config import get_settings

settings = get_settings()

# The value that opts a deployment into discovery. Anything else is taken literally.
AUTO = "auto"

# Same rationale as tunnel_check.DEFAULT_TIMEOUT: this can run inline on the test-call
# request path, and the metrics server is a container away on the compose network — it
# either answers in milliseconds or isn't there at all.
DEFAULT_TIMEOUT = 5.0

# A quick tunnel's hostname is fixed for the life of that tunnel process, so this is
# cached rather than re-fetched per call. force_refresh=True is the escape hatch for
# "the tunnel restarted underneath us" — see get_public_base_url.
_cached_url: str | None = None
_lock = asyncio.Lock()


class PublicUrlUnavailable(Exception):
    """PUBLIC_BASE_URL=auto but cloudflared couldn't be asked. Carries an
    operator-facing explanation — callers surface it rather than a bare ConnectError,
    which would just look like a network blip."""


def _configured(configured: str | None) -> str:
    """Callers pass their own settings value so they stay independently patchable in
    tests (test_call_service mocks its module-level `settings`; reading this module's
    copy instead would silently bypass that). Defaults to our own settings when the
    caller has no opinion."""
    return settings.public_base_url if configured is None else configured


def is_auto(configured: str | None = None) -> bool:
    """True when PUBLIC_BASE_URL is delegating to tunnel discovery."""
    return _configured(configured).strip().lower() == AUTO


async def _discover_quick_tunnel_url(timeout: float = DEFAULT_TIMEOUT) -> str:
    endpoint = f"{settings.cloudflared_metrics_url.rstrip('/')}/quicktunnel"
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(endpoint)
            resp.raise_for_status()
            hostname = resp.json().get("hostname")
    except (httpx.HTTPError, ValueError) as exc:
        raise PublicUrlUnavailable(
            f"PUBLIC_BASE_URL=auto, but cloudflared's metrics endpoint ({endpoint}) "
            f"could not be read: {type(exc).__name__}: {exc}. Is the tunnel running? "
            "Start it with `docker compose --profile tunnel-quick up -d`, or set "
            "PUBLIC_BASE_URL to a literal https:// URL in .env."
        ) from exc

    if not hostname:
        raise PublicUrlUnavailable(
            f"cloudflared's metrics endpoint ({endpoint}) returned no hostname. That "
            "endpoint only exists for *quick* tunnels — a named tunnel has a fixed "
            "hostname, so set PUBLIC_BASE_URL to it literally instead of 'auto'."
        )

    return f"https://{hostname}"


async def get_public_base_url(
    configured: str | None = None, *, force_refresh: bool = False
) -> str:
    """The current public base URL, with no trailing slash.

    An explicit PUBLIC_BASE_URL is returned untouched. Under `auto`, the live quick
    tunnel hostname is discovered once and cached; pass force_refresh=True to re-ask
    cloudflared, which is how a caller recovers from a tunnel that restarted (and so
    changed hostname) while this process stayed up.

    Raises PublicUrlUnavailable under `auto` when cloudflared can't be reached. Returns
    "" when PUBLIC_BASE_URL is simply unset, preserving the existing "no tunnel
    configured" behavior that the hosted-LLM path depends on.
    """
    global _cached_url

    if not is_auto(configured):
        return _configured(configured).rstrip("/")

    if _cached_url is not None and not force_refresh:
        return _cached_url

    # Serialized so a burst of concurrent calls (several tools, or api+worker startup)
    # produces one probe rather than N.
    async with _lock:
        if _cached_url is not None and not force_refresh:
            return _cached_url
        _cached_url = (await _discover_quick_tunnel_url()).rstrip("/")
        return _cached_url


def reset_cache() -> None:
    """Drop the memoized URL. For tests, and for anything that knows the tunnel changed."""
    global _cached_url
    _cached_url = None
