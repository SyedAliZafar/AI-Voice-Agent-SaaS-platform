"""Diagnose the Custom LLM (DeepSeek) path without placing a real phone call.

Why this exists: when an agent with use_custom_llm=True "doesn't work", the failure is
almost always silent — Retell dials a websocket it can't reach and the caller just gets
dead air. Nothing in our logs, nothing in the UI. This walks the same chain Retell walks
and says which link is broken.

    uv run python scripts/check_custom_llm.py

Checks, in dependency order (later ones are pointless if an earlier one fails):
  1. Config      — PUBLIC_BASE_URL / DEEPSEEK_API_KEY / RETELL_FROM_NUMBER present
  2. Tunnel      — GET {PUBLIC_BASE_URL}/health actually resolves and returns 200
  3. DeepSeek    — a real completion via llm_service, proving key + model + base_url
  4. WebSocket   — connects to wss://{PUBLIC_BASE_URL}/llm-websocket/{id} from the PUBLIC
                   internet exactly as Retell does, and runs a full response_required
                   exchange against real DeepSeek

Step 4 seeds a temporary Agent + Call row and deletes them afterwards (even on failure).
It writes to whatever DATABASE_URL points at, so run it against dev, not prod.
"""

import asyncio
import json
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import websockets
from sqlalchemy import select

from backend.config import get_settings
from backend.database import AsyncSessionLocal
from backend.models.agent import Agent
from backend.models.call import Call
from backend.models.tenant import Tenant
from backend.services import tunnel_check

settings = get_settings()

OK = "[ OK ]"
FAIL = "[FAIL]"
WARN = "[WARN]"

DIAGNOSTIC_PROMPT = (
    "You are a test harness. Reply with exactly the word: PONG. Nothing else, no "
    "punctuation, no explanation."
)


def _fail(msg: str, fix: str) -> None:
    print(f"{FAIL} {msg}")
    print(f"       fix: {fix}")
    sys.exit(1)


def check_config() -> None:
    print("1. Config")
    if not settings.public_base_url:
        _fail(
            "PUBLIC_BASE_URL is empty",
            "start the tunnel (docker compose --profile tunnel up -d), take the "
            "https://*.trycloudflare.com URL from `docker compose logs tunnel`, put it in "
            ".env, then `docker compose up -d api` (restart alone does NOT re-read .env).",
        )
    if not settings.deepseek_api_key:
        _fail("DEEPSEEK_API_KEY is empty", "set it in .env and recreate the api container.")
    print(f"{OK}   PUBLIC_BASE_URL = {settings.public_base_url}")
    print(f"{OK}   DEEPSEEK_API_KEY set ({len(settings.deepseek_api_key)} chars)")
    if not settings.retell_from_number:
        print(f"{WARN} RETELL_FROM_NUMBER is empty — fine for this check, but test calls "
              "will fail until it's set.")


async def check_tunnel() -> None:
    print("\n2. Tunnel reachability")
    url = f"{settings.public_base_url.rstrip('/')}/health"
    # Shared with test_call_service's preflight guard (backend/services/tunnel_check.py)
    # so this diagnostic and the runtime check can't silently drift apart. One request,
    # not two: a second independent GET here could flake differently than the one the
    # helper already made.
    reason = await tunnel_check.check_public_url_reachable(settings.public_base_url, timeout=20.0)
    if reason:
        _fail(
            reason,
            "the quick tunnel's hostname changes on every restart, and a long-running one "
            "can die while the container still reports 'Up'. Check `docker compose logs "
            "tunnel` for the CURRENT https://*.trycloudflare.com URL, update PUBLIC_BASE_URL, "
            "and recreate the api container.",
        )
    print(f"{OK}   {url} -> 200 (reachable)")


async def check_deepseek() -> None:
    print("\n3. DeepSeek API")
    from backend.services import llm_service

    try:
        reply = await asyncio.wait_for(
            llm_service.get_agent_response(
                DIAGNOSTIC_PROMPT, [{"role": "user", "content": "ping"}], {}
            ),
            timeout=45.0,
        )
    except TimeoutError:
        _fail("DeepSeek did not respond within 45s", "check network / DeepSeek status.")
    except Exception as exc:
        _fail(
            f"DeepSeek call raised {type(exc).__name__}: {exc}",
            "usually an invalid DEEPSEEK_API_KEY or no credit on the account. Note "
            "llm_service points base_url at https://api.deepseek.com — an OpenAI key will "
            "not work here.",
        )
    print(f"{OK}   model responded: {reply.strip()[:80]!r}")


async def check_websocket() -> None:
    """The real test: connect from the public internet the way Retell does."""
    print("\n4. Custom LLM websocket (as Retell sees it)")

    agent_id = uuid.uuid4()
    external_id = f"diagnostic_{uuid.uuid4().hex[:12]}"
    created_tenant = False

    async with AsyncSessionLocal() as db:
        # agents.tenant_id is a real FK in Postgres (the SQLite test suite doesn't enforce
        # it), so reuse an existing tenant rather than inventing one.
        existing = (await db.execute(select(Tenant).limit(1))).scalar_one_or_none()
        if existing:
            tenant_id = existing.id
        else:
            tenant_id = uuid.uuid4()
            db.add(Tenant(id=tenant_id, name="__custom_llm_diagnostic__"))
            await db.flush()
            created_tenant = True

        db.add(
            Agent(
                id=agent_id,
                tenant_id=tenant_id,
                name="__custom_llm_diagnostic__",
                system_prompt=DIAGNOSTIC_PROMPT,
                platform="retell",
                use_custom_llm=True,
            )
        )
        db.add(
            Call(
                tenant_id=tenant_id,
                agent_id=agent_id,
                caller_number="+10000000000",
                status="in_progress",
                started_at=datetime.now(UTC),
                external_id=external_id,
            )
        )
        await db.commit()

    ws_base = settings.public_base_url.replace("https://", "wss://").replace("http://", "ws://")
    ws_url = f"{ws_base.rstrip('/')}/llm-websocket/{external_id}"
    print(f"       connecting to {ws_url}")

    try:
        async with websockets.connect(ws_url, open_timeout=25, close_timeout=10) as ws:
            config = json.loads(await asyncio.wait_for(ws.recv(), timeout=25))
            if config.get("response_type") != "config":
                _fail(f"expected a config frame first, got {config}", "check retell_ws.py")
            print(f"{OK}   handshake: received config frame")

            await ws.send(json.dumps({"interaction_type": "ping_pong", "timestamp": 1}))
            pong = json.loads(await asyncio.wait_for(ws.recv(), timeout=25))
            if pong.get("response_type") != "ping_pong":
                _fail(f"expected ping_pong, got {pong}", "check retell_ws.py")
            print(f"{OK}   ping_pong round-trip")

            await ws.send(
                json.dumps(
                    {
                        "interaction_type": "response_required",
                        "response_id": 1,
                        "transcript": [{"role": "user", "content": "ping"}],
                    }
                )
            )
            reply = json.loads(await asyncio.wait_for(ws.recv(), timeout=60))
            if reply.get("response_type") != "response":
                _fail(f"expected a response frame, got {reply}", "check retell_ws.py")
            print(f"{OK}   DeepSeek answered over the socket: {reply.get('content', '')[:80]!r}")

    except Exception as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if status is not None:
            _fail(
                f"websocket rejected with HTTP {status}",
                "the tunnel is reaching something, but not our ws route. Confirm the api "
                "container is running with --proxy-headers and that retell_ws.router is "
                "registered in main.py.",
            )
        if "1008" in str(exc):
            _fail(
                "the socket opened then closed with 1008 (unknown call_id)",
                "retell_ws.py resolves the call by external_id; the seeded row wasn't "
                "visible to the API container. Are this script and the container pointed "
                "at the same DATABASE_URL? (The container uses the compose network host, "
                "the script uses whatever .env says.)",
            )
        _fail(
            f"{type(exc).__name__}: {exc}",
            "Retell would hit this same error, and the caller would just get dead air.",
        )
    finally:
        from sqlalchemy import delete

        from backend.models.call import Transcript

        async with AsyncSessionLocal() as db:
            # retell_ws.py writes a Transcript row turn-by-turn during the exchange above
            # (no cascade on transcripts.call_id), so it must go before the Call or the FK
            # delete fails and leaves both rows orphaned.
            call_row = (
                await db.execute(select(Call).where(Call.external_id == external_id))
            ).scalar_one_or_none()
            if call_row is not None:
                await db.execute(delete(Transcript).where(Transcript.call_id == call_row.id))
                await db.execute(delete(Call).where(Call.id == call_row.id))
            await db.execute(delete(Agent).where(Agent.id == agent_id))
            if created_tenant:
                await db.execute(delete(Tenant).where(Tenant.id == tenant_id))
            await db.commit()
        print("       cleaned up diagnostic rows")


async def main() -> None:
    print("Custom LLM (DeepSeek) path diagnostic\n" + "=" * 38)
    check_config()
    await check_tunnel()
    await check_deepseek()
    await check_websocket()
    print("\n" + "=" * 38)
    print("All checks passed — Retell can reach DeepSeek through this backend.")
    print("A use_custom_llm=True test call should now be answered by DeepSeek.")


if __name__ == "__main__":
    asyncio.run(main())
