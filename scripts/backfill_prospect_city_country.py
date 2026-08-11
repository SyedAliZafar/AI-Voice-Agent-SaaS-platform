"""One-off: fill in city/country on prospects discovered before those columns existed.

Rows created before `places.addressComponents` was added to the Places field mask have
`address` (a formatted string) but no structured city/country, so they group under
"Unspecified" in the operator UI. This re-fetches the structured components from Google
by each row's stored `google_place_id`.

Deliberately NOT parsing the existing `address` strings: component order varies by
country, and the failure mode is silent wrong data rather than an error. One Place
Details call per row is cheap and correct. It is also an *id* lookup, not a re-run of
the text search — a search could match a different business and write the wrong city
onto a real prospect.

CSV-imported rows (`google_place_id` starts with "csv:") are skipped: those ids aren't
real Google places, so there is nothing to look up. Give those rows a `city`/`country`
column in the CSV instead.

Usage:
    uv run python scripts/backfill_prospect_city_country.py --dry-run   # look first
    uv run python scripts/backfill_prospect_city_country.py             # then write
    uv run python scripts/backfill_prospect_city_country.py --limit 5   # billed calls

Each Place Details call is billed, so --dry-run makes no Google calls at all (it only
reports which rows *would* be fetched) and --limit caps how many are made in one run.
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import or_, select  # noqa: E402

from backend.config import get_settings  # noqa: E402
from backend.database import AsyncSessionLocal  # noqa: E402
from backend.models.prospect import Prospect  # noqa: E402
from backend.services import places_service  # noqa: E402

CSV_PLACE_ID_PREFIX = "csv:"


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List the rows that would be updated and exit. Makes no Google calls.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Cap how many rows are fetched (each is a billed Place Details call).",
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
            (
                await db.execute(
                    select(Prospect).where(or_(Prospect.city.is_(None), Prospect.country.is_(None)))
                )
            )
            .scalars()
            .all()
        )

        skipped_csv = [p for p in rows if p.google_place_id.startswith(CSV_PLACE_ID_PREFIX)]
        targets = [p for p in rows if not p.google_place_id.startswith(CSV_PLACE_ID_PREFIX)]
        if args.limit is not None:
            targets = targets[: args.limit]

        print(f"{len(rows)} row(s) missing city and/or country.")
        if skipped_csv:
            print(
                f"  skipping {len(skipped_csv)} CSV-imported row(s) — their ids aren't "
                "real Google places; set city/country via the CSV columns instead."
            )
        print(f"  {len(targets)} row(s) to fetch from Google.")

        if args.dry_run:
            for prospect in targets:
                print(f"  would fetch: {prospect.name}  ({prospect.address or 'no address'})")
            print("\nDry run — nothing written, no Google calls made.")
            return 0

        updated = 0
        unresolved = 0
        failed = 0

        for prospect in targets:
            try:
                city, country = await places_service.get_place_city_country(
                    prospect.google_place_id
                )
            except Exception as exc:  # noqa: BLE001 — one bad row must not abort the run
                failed += 1
                print(f"  FAILED  {prospect.name}: {exc}", file=sys.stderr)
                continue

            if city is None and country is None:
                # Google has no locality/country tagged for this place. Leave the row
                # alone rather than writing a guess.
                unresolved += 1
                print(f"  no components returned: {prospect.name}")
                continue

            # Only fill blanks — never overwrite a value already set (a later discovery
            # run, or an operator, may have supplied a better one).
            if city and not prospect.city:
                prospect.city = city
            if country and not prospect.country:
                prospect.country = country
            updated += 1
            print(f"  {prospect.name} -> city={city!r} country={country!r}")

        await db.commit()

    print(f"\nDone. {updated} updated, {unresolved} unresolved, {failed} failed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
