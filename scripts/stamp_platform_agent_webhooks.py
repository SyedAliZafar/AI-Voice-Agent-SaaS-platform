"""Point Retell dashboard ("platform") agents at our CURRENT public webhook URL.

Local agents (built in the app) get their webhook_url stamped automatically on every
create/update — see retell_adapter and ADR-012. Platform agents (an external_agent_id,
built in Retell's own dashboard) can't be stamped that way: the app didn't provision
them, so nothing re-points them when the tunnel hostname changes. On the quick tunnel
(PUBLIC_BASE_URL=auto) that hostname changes on every restart, which silently breaks
call_ended / call_analyzed delivery until someone re-pastes the URL in the dashboard.

This script does that re-paste over Retell's API instead:

    uv run python scripts/stamp_platform_agent_webhooks.py                # auto-detect agents
    uv run python scripts/stamp_platform_agent_webhooks.py agent_abc123   # explicit ids
    uv run python scripts/stamp_platform_agent_webhooks.py --dry-run

Run it after any quick-tunnel restart. With a named tunnel (fixed hostname) you don't
need it — set the webhook once in the dashboard and forget it.

Which agents get stamped, when no ids are passed:
  1. $RETELL_PLATFORM_AGENT_IDS (comma-separated), if set; else
  2. every distinct calls.external_agent_id seen in the DB.

It only PATCHes webhook_url. Nothing else about the agent is touched.
"""

import asyncio
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx
from sqlalchemy import select

from backend.config import get_settings
from backend.database import AsyncSessionLocal
from backend.models.call import Call
from backend.services import public_url

# This is an operator tool, not a service — mute the SQLAlchemy engine echo the app
# config turns on in dev (it re-raises its own logger to INFO on import, so a plain
# setLevel here loses the race) so it doesn't bury the lines that matter.
logging.disable(logging.INFO)

settings = get_settings()
BASE_URL = "https://api.retellai.com"

OK = "[ OK ]"
FAIL = "[FAIL]"
SKIP = "[SKIP]"


async def _resolve_agent_ids(explicit: list[str]) -> list[str]:
    if explicit:
        return explicit

    env = os.environ.get("RETELL_PLATFORM_AGENT_IDS", "").strip()
    if env:
        return [a.strip() for a in env.split(",") if a.strip()]

    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(
                select(Call.external_agent_id)
                .where(Call.external_agent_id.is_not(None))
                .distinct()
            )
        ).scalars().all()
    return sorted(rows)


async def _current_webhook_url() -> str:
    base = await public_url.get_public_base_url(force_refresh=True)
    if not base:
        raise SystemExit(
            f"{FAIL} PUBLIC_BASE_URL is unset / unresolvable — no public URL to stamp. "
            "Start the tunnel, or set PUBLIC_BASE_URL to a literal https:// URL."
        )
    return f"{base}/webhooks/retell"


async def _stamp(client: httpx.AsyncClient, agent_id: str, webhook_url: str, dry_run: bool) -> bool:
    try:
        got = await client.get(f"{BASE_URL}/get-agent/{agent_id}")
        got.raise_for_status()
    except httpx.HTTPError as exc:
        print(f"{FAIL} {agent_id}: cannot read agent ({exc!r})")
        return False

    current = got.json().get("webhook_url")
    if current == webhook_url:
        print(f"{SKIP} {agent_id}: already points at {webhook_url}")
        return True
    if dry_run:
        print(f"{OK}   {agent_id}: would set webhook_url {current!r} -> {webhook_url!r}")
        return True

    try:
        resp = await client.patch(
            f"{BASE_URL}/update-agent/{agent_id}", json={"webhook_url": webhook_url}
        )
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        print(f"{FAIL} {agent_id}: PATCH failed ({exc!r})")
        return False

    print(f"{OK}   {agent_id}: webhook_url {current!r} -> {webhook_url!r}")
    return True


async def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    dry_run = "--dry-run" in sys.argv[1:]

    if not settings.retell_api_key:
        print(f"{FAIL} RETELL_API_KEY is not set")
        return 1

    webhook_url = await _current_webhook_url()
    agent_ids = await _resolve_agent_ids(args)
    if not agent_ids:
        print(
            f"{FAIL} no platform agents to stamp — pass agent ids as arguments, set "
            "RETELL_PLATFORM_AGENT_IDS, or place at least one call through a platform agent first."
        )
        return 1

    print(f"Target webhook URL: {webhook_url}")
    print(f"Agents: {', '.join(agent_ids)}")
    if dry_run:
        print("(dry run — no changes will be sent)")
    print()

    headers = {"Authorization": f"Bearer {settings.retell_api_key}"}
    async with httpx.AsyncClient(headers=headers, timeout=15.0) as client:
        results = [await _stamp(client, aid, webhook_url, dry_run) for aid in agent_ids]

    ok = all(results)
    print()
    print(f"{'All agents current.' if ok else 'Some agents failed — see above.'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
