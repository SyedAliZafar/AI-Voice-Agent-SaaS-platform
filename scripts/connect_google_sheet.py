"""Connect a tenant's prospect list to a Google Sheet, and verify the connection works.

    uv run python scripts/connect_google_sheet.py --url "https://docs.google.com/spreadsheets/d/<ID>/edit"
    uv run python scripts/connect_google_sheet.py --url "<...>" --sheet-name "Prospects"
    uv run python scripts/connect_google_sheet.py --check      # verify what's already connected

Writes one `integrations` row (kind="sheet", provider="google_sheets") holding ONLY the
spreadsheet id and tab name. The service-account key is never stored in the database —
it stays in the file named by GOOGLE_SHEETS_CREDENTIALS_FILE. See
backend/services/sheets_service.py.

Before running, the sheet must be shared with the service account's email as an EDITOR.
This script prints that email for you and does a real read, so a missing share fails here
with a clear message rather than later behind a button.
"""

import argparse
import asyncio
import json
import re
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.config import get_settings  # noqa: E402
from backend.database import AsyncSessionLocal  # noqa: E402
from backend.services import integration_config_service, sheets_service  # noqa: E402

DEMO_TENANT_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")

# Accepts a full edit URL or a bare id — operators paste whichever is in their clipboard.
_URL_RE = re.compile(r"/spreadsheets/d/([a-zA-Z0-9-_]+)")


def spreadsheet_id_from(value: str) -> str:
    match = _URL_RE.search(value)
    return match.group(1) if match else value.strip()


def service_account_email() -> str:
    """Read the client_email out of the key file — the address the sheet must be shared
    with. Getting this wrong is the single most common setup failure (a 403 that looks
    like a bad key but is actually a missing share), so it's printed every run."""
    path = get_settings().google_sheets_credentials_file
    if not path:
        return "(GOOGLE_SHEETS_CREDENTIALS_FILE is not set)"
    try:
        return str(json.loads(Path(path).read_text(encoding="utf-8")).get("client_email", "?"))
    except (OSError, ValueError) as exc:
        return f"(could not read {path}: {exc})"


async def run(
    tenant_id: uuid.UUID,
    url: str | None,
    sheet_name: str,
    check_only: bool,
    push_only: bool = False,
) -> int:
    print(f"Service account: {service_account_email()}")
    print("The spreadsheet must be shared with that address as an Editor.\n")

    async with AsyncSessionLocal() as db:
        if url:
            spreadsheet_id = spreadsheet_id_from(url)
            await integration_config_service.upsert(
                db,
                tenant_id,
                "sheet",
                "google_sheets",
                {"spreadsheet_id": spreadsheet_id, "sheet_name": sheet_name},
                True,
            )
            print(f"Connected spreadsheet {spreadsheet_id} (tab '{sheet_name}').")

        integration = await integration_config_service.get(db, tenant_id, "sheet")
        if not integration:
            print("No sheet connected. Re-run with --url to connect one.", file=sys.stderr)
            return 1

        config = integration.config or {}
        sid = str(config.get("spreadsheet_id") or "")
        tab = str(config.get("sheet_name") or "Sheet1")

        try:
            tabs = await sheets_service.list_tabs(sid)
        except sheets_service.SheetSyncError as exc:
            print(f"\nFAILED: {exc}", file=sys.stderr)
            return 1
        print(f"Tabs in this spreadsheet: {', '.join(repr(t) for t in tabs)}")

        if tab not in tabs:
            if check_only:
                print(f"\nTab '{tab}' does not exist yet — re-run without --check to create it.")
                return 1
            print(f"Creating tab '{tab}'...")
            await sheets_service.create_tab(sid, tab)
            tabs.append(tab)

        print(f"\nVerifying read access to {sid} (tab '{tab}')...")
        try:
            grid = await sheets_service._read_grid(sid, tab)
        except sheets_service.SheetSyncError as exc:
            print(f"\nFAILED: {exc}", file=sys.stderr)
            return 1
        print(f"OK — the tab currently has {len(grid)} row(s).")

        if check_only:
            return 0

        # The sync overwrites A1:L{n} on this tab. A tab holding rows whose header isn't
        # ours is somebody's real work, not a stale prospect list — refuse rather than
        # destroy it. This exists because the first real run was pointed at a live
        # five-tab business tracker; the default tab name is no guarantee of an empty tab.
        if grid and grid[0][: len(sheets_service.HEADER)] != sheets_service.HEADER:
            print(
                f"\nREFUSING TO SYNC: tab '{tab}' already holds {len(grid)} row(s) whose\n"
                f"header is not the prospect layout:\n"
                f"  found:    {grid[0][:8]}\n"
                f"  expected: {sheets_service.HEADER[:8]}\n\n"
                "Syncing would overwrite columns A-L and destroy that data. Point --sheet-name\n"
                "at a new or empty tab instead.",
                file=sys.stderr,
            )
            return 1

        print(
            "\nPushing the database over the sheet (no pull)..."
            if push_only
            else "\nRunning the sync (pull, then push)..."
        )
        stats = await sheets_service.sync(db, tenant_id, sid, tab, pull=not push_only)
        print(f"  {stats}")
        print(
            f"\nDone. The sheet now holds {stats['written']} prospect row(s).\n"
            "In the sheet: hide column A (the id), and turn column H into a checkbox\n"
            "(Insert -> Tick box) to use it as the 'call again' queue."
        )
        return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant-id", type=uuid.UUID, default=DEMO_TENANT_ID)
    parser.add_argument("--url", help="Spreadsheet URL or bare id")
    parser.add_argument("--sheet-name", default="Sheet1", help="Tab name (default: Sheet1)")
    parser.add_argument(
        "--check", action="store_true", help="Verify access only; don't sync or reconnect"
    )
    parser.add_argument(
        "--push-only",
        action="store_true",
        help=(
            "Overwrite the sheet from the database without reading it first. Use after "
            "repairing data out-of-band -- an ordinary sync would pull the sheet's stale "
            "values back over the repair."
        ),
    )
    args = parser.parse_args()

    raise SystemExit(
        asyncio.run(run(args.tenant_id, args.url, args.sheet_name, args.check, args.push_only))
    )


if __name__ == "__main__":
    main()
