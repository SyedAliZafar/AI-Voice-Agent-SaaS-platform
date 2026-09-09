"""Remove prospects that have never been called — the "Not called" rows across every
category on the /prospects dashboard (status == "not_called").

Deletes each prospect's Call rows first (Call.prospect_id has no ON DELETE CASCADE),
then the Prospect rows themselves. Dry-run by default; pass --yes to commit. Hits the
SHARED Neon database — see RUN.md.

    uv run python scripts/remove_uncalled_prospects.py                # dry run, demo tenant
    uv run python scripts/remove_uncalled_prospects.py --yes          # commit
    uv run python scripts/remove_uncalled_prospects.py --tenant-id <uuid> --yes
"""

import argparse
import asyncio
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import delete, select  # noqa: E402

from backend.database import AsyncSessionLocal  # noqa: E402
from backend.models.call import Call  # noqa: E402
from backend.models.prospect import Prospect  # noqa: E402

DEMO_TENANT_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant-id", type=uuid.UUID, default=DEMO_TENANT_ID)
    parser.add_argument("--yes", action="store_true", help="commit the deletion")
    args = parser.parse_args()

    async with AsyncSessionLocal() as db:
        prospects = list(
            (
                await db.execute(
                    select(Prospect).where(
                        Prospect.tenant_id == args.tenant_id,
                        Prospect.status == "not_called",
                    )
                )
            ).scalars()
        )
        if not prospects:
            print(f"No uncalled prospects for tenant {args.tenant_id}.")
            return 0

        ids = [p.id for p in prospects]
        by_city: dict[str, int] = {}
        for p in prospects:
            key = p.city or "Unspecified"
            by_city[key] = by_city.get(key, 0) + 1

        print(f"Tenant {args.tenant_id} — {len(prospects)} uncalled prospect(s):")
        for city, count in sorted(by_city.items()):
            print(f"  {city}: {count}")

        if not args.yes:
            print("\nDry run. Re-run with --yes to commit.")
            return 0

        await db.execute(delete(Call).where(Call.prospect_id.in_(ids)))
        await db.execute(delete(Prospect).where(Prospect.id.in_(ids)))
        await db.commit()
        print(f"\nDeleted {len(prospects)} prospect(s).")
        return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
