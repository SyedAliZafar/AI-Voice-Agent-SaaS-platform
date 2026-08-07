"""Dev-only: seed the single hardcoded HVAC/solar outbound test agent.

This is a validation pass, not the final architecture (no category/knowledge-base data
model exists yet — see phase4.md / CONTEXT.md's "what not to build" list). There is no
CRUD route or UI flow for creating an agent with a pre-written prompt from a file, so
this mirrors scripts/seed_booking_tool_config.py's pattern: a dev-only script that
inserts/upserts directly rather than adding new API surface for a one-off.

The knowledge-base markdown (frontend/dashboardDesiging/hvac-solar-outbound-knowledge-v1.md)
is read and stored verbatim as Agent.system_prompt — not summarized, not restructured
into CONTEXT.md's [ROLE]/[GUARDRAILS]/... scaffold. That file stays the single source of
truth; this script doesn't duplicate its content anywhere else.

use_custom_llm=True is required, not a default choice: ADR-003 tool execution (and so
book_discovery_call/flag_for_human_review) only runs on the custom-LLM path
(backend/api/retell_ws.py). Retell's hosted-LLM path never calls our tools at all.

Usage:
    uv run python scripts/seed_hvac_solar_outbound_agent.py

Then, once PUBLIC_BASE_URL (tunnel) and RETELL_FROM_NUMBER are set (see RUN.md), place a
real call via the existing "Test call" button on /agents/{agent_id} in the dashboard, or:
    curl -X POST -H "Authorization: Bearer <token>" \\
        -H "Content-Type: application/json" \\
        -d '{"to_number": "+1..."}' \\
        http://localhost:8000/api/agents/{agent_id}/test-call
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

# Matches scripts/dev_token.py's DEMO_TENANT_ID so a freshly seeded backend and the
# dashboard agree without further configuration.
DEMO_TENANT_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")

AGENT_NAME = "HVAC/Solar Outbound — Test v1"

KNOWLEDGE_BASE_PATH = (
    Path(__file__).resolve().parent.parent
    / "frontend"
    / "dashboardDesiging"
    / "hvac-solar-outbound-knowledge-v1.md"
)


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tenant-id",
        type=uuid.UUID,
        default=DEMO_TENANT_ID,
        help=f"Tenant to create the agent under (default: the demo tenant {DEMO_TENANT_ID})",
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

    if not KNOWLEDGE_BASE_PATH.exists():
        print(f"ERROR: knowledge base file not found: {KNOWLEDGE_BASE_PATH}", file=sys.stderr)
        return 1

    system_prompt = KNOWLEDGE_BASE_PATH.read_text(encoding="utf-8")

    async with AsyncSessionLocal() as db:
        existing = (
            await db.execute(
                select(Agent).where(
                    Agent.tenant_id == args.tenant_id,
                    Agent.name == AGENT_NAME,
                )
            )
        ).scalar_one_or_none()

        if existing:
            existing.system_prompt = system_prompt
            existing.use_custom_llm = True
            existing.platform = "retell"
            await db.commit()
            print(f"Updated existing agent {existing.id} ({AGENT_NAME})")
            agent_id = existing.id
        else:
            agent = Agent(
                tenant_id=args.tenant_id,
                name=AGENT_NAME,
                system_prompt=system_prompt,
                platform="retell",
                use_custom_llm=True,
                llm_model="",
            )
            db.add(agent)
            await db.commit()
            await db.refresh(agent)
            print(f"Created agent {agent.id} ({AGENT_NAME})")
            agent_id = agent.id

    print()
    print("Before placing a real test call, confirm (see RUN.md):")
    print("  - PUBLIC_BASE_URL is set and reachable (use_custom_llm requires the tunnel)")
    print("  - RETELL_FROM_NUMBER is set")
    print()
    print(f"Then use the dashboard's Test call button on /agents/{agent_id},")
    print(f"or POST /api/agents/{agent_id}/test-call directly.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
