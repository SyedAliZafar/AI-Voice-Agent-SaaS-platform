"""Merge prospect rows that share a phone_match_key — the E.164-vs-national-format
duplicates that predate the match-key import dedupe (e.g. "+442077335265" and
"020 7733 5265" for the same London line).

    uv run python scripts/merge_duplicate_prospects.py            # dry run
    uv run python scripts/merge_duplicate_prospects.py --apply    # execute
    uv run python scripts/merge_duplicate_prospects.py --apply --tenant-id <uuid>

Keeper per group = the row with the most Call rows, tie-broken by a non-default status,
then by oldest created_at. Losers' calls are repointed to the keeper, the losers are
deleted, and the keeper's call_count / last_called_at / status are resynced from its
Call rows. Hits the SHARED Neon database — see RUN.md.
"""

import argparse
import asyncio
import sys
import uuid
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import func, select, update  # noqa: E402

from backend.config import get_settings  # noqa: E402
from backend.database import AsyncSessionLocal  # noqa: E402
from backend.models.call import Call  # noqa: E402
from backend.models.prospect import Prospect  # noqa: E402
from backend.services import call_service, prospect_service  # noqa: E402

DEMO_TENANT_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")


async def run(tenant_id: uuid.UUID, apply: bool) -> None:
    async with AsyncSessionLocal() as db:
        rows = (
            (await db.execute(select(Prospect).where(Prospect.tenant_id == tenant_id)))
            .scalars()
            .all()
        )
        call_counts = dict(
            (
                await db.execute(
                    select(Call.prospect_id, func.count())
                    .where(Call.tenant_id == tenant_id, Call.prospect_id.is_not(None))
                    .group_by(Call.prospect_id)
                )
            ).all()
        )

        groups: dict[str, list[Prospect]] = defaultdict(list)
        for p in rows:
            key = prospect_service.phone_match_key(p.phone)
            if key:
                groups[key].append(p)

        touched: set[uuid.UUID] = set()
        merged = 0
        for key, members in groups.items():
            if len(members) < 2:
                continue

            members.sort(
                key=lambda p: (
                    call_counts.get(p.id, 0),
                    p.status != "not_called",
                    -p.created_at.timestamp(),
                ),
                reverse=True,
            )
            keeper, *losers = members
            print(f"\nkey {key}: keep {keeper.name!r} ({keeper.phone}, {keeper.status})")
            for loser in losers:
                n = call_counts.get(loser.id, 0)
                print(f"  merge {loser.name!r} ({loser.phone}, {loser.status}) — {n} calls")
                if apply:
                    await db.execute(
                        update(Call)
                        .where(Call.prospect_id == loser.id)
                        .values(prospect_id=keeper.id)
                    )
                    await db.delete(loser)
                    touched.add(keeper.id)
                    merged += 1

        if not apply:
            print("\n(dry run — pass --apply to execute)")
            return

        await db.commit()
        await call_service.resync_prospects_from_calls(db, tenant_id, touched)
        print(f"\nmerged {merged} row(s); resynced {len(touched)} keeper(s)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant-id", type=uuid.UUID, default=DEMO_TENANT_ID)
    parser.add_argument("--apply", action="store_true", help="Execute; default is a dry run")
    args = parser.parse_args()

    settings = get_settings()
    if settings.environment != "development" and args.apply:
        print(f"ERROR: refusing to --apply with ENVIRONMENT={settings.environment!r}.")
        raise SystemExit(1)

    asyncio.run(run(args.tenant_id, args.apply))


if __name__ == "__main__":
    main()
