"""Dev-only: upsert a book_appointment ToolConfig row for an agent.

There is no CRUD route for ToolConfig yet (phase4.md Session 2) — retell_ws.py reads
per-agent tool credentials (calendar_id/calendar_api_key/crm_api_key, ...) out of
ToolConfig.config and flattens them into caller_context, but nothing in the API lets you
write one. This exists to unblock manually verifying ADR-009's barge-in-during-a-tool-call
behavior (CONTEXT.md) against a real Cal.com sandbox event type without hand-writing
asyncio/SQLAlchemy each time.

Usage:
    uv run python scripts/seed_booking_tool_config.py \\
        --agent-id <uuid> --calendar-id <cal.com event type id> --calendar-api-key cal_test_...

Upserts (by agent_id + tool_type="book_appointment") rather than always inserting, so
re-running with a rotated key doesn't leave stale duplicate rows.
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
from backend.models.agent import Agent, ToolConfig  # noqa: E402


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent-id", type=uuid.UUID, required=True)
    parser.add_argument("--calendar-id", required=True, help="Cal.com eventTypeId")
    parser.add_argument("--calendar-api-key", required=True, help="Cal.com API key (cal_live_...)")
    parser.add_argument(
        "--calendar-timezone",
        default="UTC",
        help=(
            "IANA timezone the caller's spoken times are in, e.g. Europe/Berlin. The LLM "
            "usually emits a naive datetime, and this decides what wall-clock time that "
            "means (default: UTC)."
        ),
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

    async with AsyncSessionLocal() as db:
        agent = (
            await db.execute(select(Agent).where(Agent.id == args.agent_id))
        ).scalar_one_or_none()
        if not agent:
            print(f"ERROR: no agent with id {args.agent_id}", file=sys.stderr)
            return 1

        existing = (
            await db.execute(
                select(ToolConfig).where(
                    ToolConfig.agent_id == args.agent_id,
                    ToolConfig.tool_type == "book_appointment",
                )
            )
        ).scalar_one_or_none()

        config = {
            "calendar_id": args.calendar_id,
            "calendar_api_key": args.calendar_api_key,
            "calendar_timezone": args.calendar_timezone,
        }
        if existing:
            existing.config = config
            print(f"Updated existing ToolConfig {existing.id} for agent {args.agent_id}")
        else:
            db.add(ToolConfig(agent_id=args.agent_id, tool_type="book_appointment", config=config))
            print(f"Created ToolConfig for agent {args.agent_id}")

        await db.commit()

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
