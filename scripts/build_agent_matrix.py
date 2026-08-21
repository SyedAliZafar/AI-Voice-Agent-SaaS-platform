"""Dev-only: create/update every (style x service x industry) leaf agent from the
scripts/agent_templates module system, mirroring seed_hvac_solar_outbound_agent.py's
direct-insert pattern (no CRUD route for bulk creation exists).

use_custom_llm=True on every row for the same reason seed_hvac_solar_outbound_agent.py
sets it: ADR-003 tool execution (book_discovery_call/flag_for_human_review) only runs on
the custom-LLM path (backend/api/retell_ws.py) — Retell's hosted-LLM path never calls our
tools at all.

Usage:
    uv run python scripts/build_agent_matrix.py                 # every combination
    uv run python scripts/build_agent_matrix.py --style short_quick --service ai_automation
    uv run python scripts/build_agent_matrix.py --industry roofing
"""

import argparse
import asyncio
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from backend.config import get_settings  # noqa: E402
from backend.database import AsyncSessionLocal  # noqa: E402
from backend.models.agent import Agent  # noqa: E402
from scripts.agent_templates.compose import agent_name, compose  # noqa: E402
from scripts.agent_templates.industries import INDUSTRIES  # noqa: E402
from scripts.agent_templates.services import SERVICES  # noqa: E402
from scripts.agent_templates.styles import STYLES  # noqa: E402

DEMO_TENANT_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")


async def upsert(db, tenant_id: uuid.UUID, name: str, system_prompt: str) -> tuple[uuid.UUID, bool]:
    existing = (
        await db.execute(
            select(Agent).where(Agent.tenant_id == tenant_id, Agent.name == name)
        )
    ).scalar_one_or_none()

    if existing:
        existing.system_prompt = system_prompt
        existing.use_custom_llm = True
        existing.platform = "retell"
        await db.commit()
        return existing.id, False

    agent = Agent(
        tenant_id=tenant_id,
        name=name,
        system_prompt=system_prompt,
        platform="retell",
        use_custom_llm=True,
        llm_model="",
    )
    db.add(agent)
    await db.commit()
    await db.refresh(agent)
    return agent.id, True


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant-id", type=uuid.UUID, default=DEMO_TENANT_ID)
    parser.add_argument("--style", action="append", choices=list(STYLES), help="Repeatable; default: all")
    parser.add_argument("--service", action="append", choices=list(SERVICES), help="Repeatable; default: all")
    parser.add_argument("--industry", action="append", choices=list(INDUSTRIES), help="Repeatable; default: all")
    args = parser.parse_args()

    settings = get_settings()
    if settings.environment != "development":
        print(
            f"ERROR: refusing to run with ENVIRONMENT={settings.environment!r}. "
            "This script is development-only.",
            file=sys.stderr,
        )
        return 1

    styles = args.style or list(STYLES)
    services = args.service or list(SERVICES)
    industries = args.industry or list(INDUSTRIES)

    combos = [
        (s, sv, i) for s in styles for sv in services for i in industries
    ]

    print(f"Building {len(combos)} agent(s) for tenant {args.tenant_id}:")
    print()

    async with AsyncSessionLocal() as db:
        for style_key, service_key, industry_key in combos:
            name = agent_name(style_key, service_key, industry_key)
            prompt = compose(style_key, service_key, industry_key)
            agent_id, created = await upsert(db, args.tenant_id, name, prompt)
            verb = "Created" if created else "Updated"
            print(f"  {verb} {agent_id}  {name}")

    print()
    print("None of these are provisioned on Retell yet (no phone number, no test call) —")
    print("that happens per-agent via the dashboard's Test call button, same as any other agent.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
