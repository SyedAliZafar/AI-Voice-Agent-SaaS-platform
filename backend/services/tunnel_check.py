"""Is our public URL actually reachable from the internet?

Retell dials *into* us for the custom-LLM path (the websocket in backend/api/retell_ws.py)
and for webhook delivery. If PUBLIC_BASE_URL points at a dead tunnel, none of that
arrives and the caller just gets dead air — with nothing in our logs, because nothing
ever reached us.

Checking that the URL is *set* is not enough: a cloudflared quick tunnel's hostname
changes on every restart and the tunnel can die while the container still reports "Up" in
`docker compose ps`. So the only trustworthy check is an actual request.

Used in two places, deliberately sharing one implementation so the diagnostic and the
runtime guard can't drift apart:
  - test_call_service._provision_custom_llm_agent — refuses to spend a real phone call
    on an unreachable URL
  - scripts/check_custom_llm.py — step 2 of the offline diagnostic
"""

import httpx

# Short on purpose: this runs inline on the test-call request path, and a dead tunnel
# fails at DNS in milliseconds anyway. A hang here would just be a slower way to learn
# the same thing.
DEFAULT_TIMEOUT = 5.0


async def check_public_url_reachable(base_url: str, timeout: float = DEFAULT_TIMEOUT) -> str | None:
    """GET {base_url}/health.

    Returns None when reachable, else a short human-readable reason suitable for
    appending to an operator-facing error message. Returns a reason rather than raising
    so callers decide the error type — TestCallError in the request path, sys.exit in
    the diagnostic script.
    """
    if not base_url:
        return "PUBLIC_BASE_URL is empty"

    url = f"{base_url.rstrip('/')}/health"
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(url)
    except httpx.ConnectError as exc:
        # The common case: the tunnel hostname no longer resolves.
        return f"cannot connect to {url} ({exc})"
    except httpx.TimeoutException:
        return f"{url} timed out after {timeout:g}s"
    except httpx.HTTPError as exc:
        return f"{url} failed: {type(exc).__name__}: {exc}"

    if resp.status_code != 200:
        return f"{url} returned HTTP {resp.status_code} (expected 200)"

    return None
