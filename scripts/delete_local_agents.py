"""Delete a tenant's LOCAL agents — the "Your agents" tab, i.e. rows in the `agents`
table this backend provisions and configures. The "Retell agents" tab is the live
platform roster and is untouched by this (nothing here talks to Retell).

Hits the SHARED Neon database — see RUN.md. Dry-run by default; pass --yes to commit.

None of the agents.id foreign keys are ON DELETE CASCADE, so this:
  - NULLs `calls.agent_id` and `leads.agent_id` (both nullable) to keep that history
  - deletes the agent's `phone_numbers` and `tool_configs` rows
  - deletes the `agents` rows

    uv run python scripts/delete_local_agents.py                     # dry run, demo tenant
    uv run python scripts/delete_local_agents.py --yes               # commit
    uv run python scripts/delete_local_agents.py --tenant-id <uuid> --yes
"""

import argparse
import asyncio
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import delete, func, select, update  # noqa: E402

from backend.database import AsyncSessionLocal  # noqa: E402
from backend.models.agent import Agent, PhoneNumber, ToolConfig  # noqa: E402
from backend.models.call import Call  # noqa: E402
from backend.models.lead import Lead  # noqa: E402

DEMO_TENANT_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant-id", type=uuid.UUID, default=DEMO_TENANT_ID)
    parser.add_argument("--yes", action="store_true", help="commit the deletion")
    args = parser.parse_args()

    async with AsyncSessionLocal() as db:
        agents = list(
            (
                await db.execute(select(Agent).where(Agent.tenant_id == args.tenant_id))
            ).scalars()
        )
        if not agents:
            print(f"No local agents for tenant {args.tenant_id}.")
            return 0

        ids = [a.id for a in agents]
        calls = await db.scalar(
            select(func.count()).select_from(Call).where(Call.agent_id.in_(ids))
        )
        leads = await db.scalar(
            select(func.count()).select_from(Lead).where(Lead.agent_id.in_(ids))
        )
        phones = await db.scalar(
            select(func.count()).select_from(PhoneNumber).where(PhoneNumber.agent_id.in_(ids))
        )
        tools = await db.scalar(
            select(func.count()).select_from(ToolConfig).where(ToolConfig.agent_id.in_(ids))
        )

        print(f"Tenant {args.tenant_id} — {len(agents)} local agent(s):")
        for a in agents:
            print(f"  {a.id}  [{a.platform}]  {a.name}")
        print(
            f"\nDependents: {calls} call(s) and {leads} lead(s) will be detached "
            f"(agent_id -> NULL); {phones} phone number(s) and {tools} tool config(s) "
            f"will be deleted."
        )

        if not args.yes:
            print("\nDry run. Re-run with --yes to commit.")
            return 0

        await db.execute(
            update(Call).where(Call.agent_id.in_(ids)).values(agent_id=None)
        )
        await db.execute(
            update(Lead).where(Lead.agent_id.in_(ids)).values(agent_id=None)
        )
        await db.execute(delete(PhoneNumber).where(PhoneNumber.agent_id.in_(ids)))
        await db.execute(delete(ToolConfig).where(ToolConfig.agent_id.in_(ids)))
        await db.execute(delete(Agent).where(Agent.id.in_(ids)))
        await db.commit()
        print(f"\nDeleted {len(agents)} agent(s).")
        return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
