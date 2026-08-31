"""One-off: collapse existing prospect categories onto the canonical verticals.

`prospects.category` was written straight through from Google's free-text
`primaryTypeDisplayName` (and the CSV `niche` column), so the operator's category
filter accumulated a bucket per stray discovery run — "Dental Clinic", "British
Restaurant", "Services", "General Contractor". Ingest now runs every value through
`prospect_service.normalize_category`; this brings the rows written before that in line.

Anything that isn't Roofing or Solar becomes NULL, which the UI renders as
"Unspecified". No row is deleted and nothing else on the row is touched — only the
label is dropped, so a prospect stays callable and stays in the list.

Usage:
    uv run python scripts/normalize_prospect_categories.py --dry-run   # look first
    uv run python scripts/normalize_prospect_categories.py             # then write

Note this writes to the SHARED database (see RUN.md) — a run lands on teammates too.
"""

import argparse
import asyncio
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from backend.config import get_settings  # noqa: E402
from backend.database import AsyncSessionLocal  # noqa: E402
from backend.models.prospect import Prospect  # noqa: E402
from backend.services.prospect_service import normalize_category  # noqa: E402


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would change and exit without writing.",
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
        rows = (
            (await db.execute(select(Prospect).where(Prospect.category.is_not(None))))
            .scalars()
            .all()
        )

        changes: Counter[tuple[str, str]] = Counter()
        for prospect in rows:
            old = prospect.category
            new = normalize_category(old)
            if new == old:
                continue
            changes[(old, new or "Unspecified")] += 1
            if not args.dry_run:
                prospect.category = new

        total = sum(changes.values())
        for (old, new), count in sorted(changes.items(), key=lambda item: -item[1]):
            print(f"  {count:>4}  {old!r} -> {new}")
        print(f"\n{total} of {len(rows)} labelled row(s) affected.")

        if args.dry_run:
            print("Dry run — nothing written.")
            return 0

        await db.commit()

    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
