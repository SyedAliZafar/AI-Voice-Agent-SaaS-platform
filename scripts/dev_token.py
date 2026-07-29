"""Dev-only: seed the demo tenant and mint a bearer token for it.

Usage:
    uv run python scripts/dev_token.py

Prints a JWT signed with JWT_SECRET carrying a tenant_id claim, which is what
backend/api/deps.py:get_current_tenant expects. Paste it into the dashboard (it's
stored as `auth_token` in localStorage — frontend/src/lib/api.ts sends it as a bearer
header), or use it directly:

    curl -H "Authorization: Bearer <token>" http://localhost:8000/api/agents

This exists because there is no real login flow yet — CLERK_SECRET_KEY is configured
but unused. When Clerk is wired up, tokens come from Clerk and this script goes away;
get_current_tenant keeps working as long as the token carries a tenant_id claim.

NEVER run this against a production database, and never ship JWT_SECRET's default value.
"""

import argparse
import asyncio
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

# See setup_retell_number.py — running a script file directly puts scripts/ on sys.path,
# not the repo root, so the local `backend` package isn't importable without this.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jose import jwt  # noqa: E402
from sqlalchemy import select  # noqa: E402

from backend.config import get_settings  # noqa: E402
from backend.database import AsyncSessionLocal  # noqa: E402
from backend.models.tenant import Tenant  # noqa: E402

# Matches DEMO_TENANT_ID in frontend/src/lib/constants.ts so the dashboard and a
# freshly seeded backend agree without further configuration.
DEMO_TENANT_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
DEMO_TENANT_NAME = "Demo Tenant"


async def ensure_tenant(tenant_id: uuid.UUID) -> bool:
    """Create the tenant row if absent. Returns True if it was created."""
    async with AsyncSessionLocal() as db:
        existing = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
        if existing.scalar_one_or_none():
            return False

        db.add(Tenant(id=tenant_id, name=DEMO_TENANT_NAME, plan="trial"))
        await db.commit()
        return True


def mint_token(tenant_id: uuid.UUID, days: int) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    claims = {
        "tenant_id": str(tenant_id),
        "sub": f"dev-user@{tenant_id}",
        "iat": now,
        "exp": now + timedelta(days=days),
    }
    return jwt.encode(claims, settings.jwt_secret, algorithm="HS256")


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tenant-id",
        type=uuid.UUID,
        default=DEMO_TENANT_ID,
        help=f"Tenant to mint for (default: the demo tenant {DEMO_TENANT_ID})",
    )
    parser.add_argument(
        "--days", type=int, default=30, help="Token lifetime in days (default: 30)"
    )
    parser.add_argument(
        "--no-seed",
        action="store_true",
        help="Mint only; don't create the tenant row if it's missing",
    )
    args = parser.parse_args()

    settings = get_settings()
    if settings.environment != "development":
        print(
            f"ERROR: refusing to run with ENVIRONMENT={settings.environment!r}. "
            "This script is development-only.",
            file=sys.stderr,
        )
        return 1

    if not args.no_seed:
        try:
            created = await ensure_tenant(args.tenant_id)
        except Exception as exc:  # noqa: BLE001 — surface any DB error as actionable text
            print(
                f"ERROR: could not reach the database ({exc}).\n"
                "Is Postgres up (docker compose up -d postgres) and migrated "
                "(uv run alembic upgrade head)?",
                file=sys.stderr,
            )
            return 1
        print(f"Tenant {args.tenant_id}: {'created' if created else 'already exists'}")

    token = mint_token(args.tenant_id, args.days)

    print()
    print(f"Bearer token (valid {args.days}d):")
    print()
    print(token)
    print()
    print("Use it with curl:")
    print(f'  curl -H "Authorization: Bearer {token[:24]}..." http://localhost:8000/api/agents')
    print()
    print("Or in the dashboard — run this in the browser console on http://localhost:3000,")
    print("then reload:")
    print(f'  localStorage.setItem("auth_token", "{token}")')
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
