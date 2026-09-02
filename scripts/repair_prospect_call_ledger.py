"""One-off repair for prospects whose outreach ledger drifted from their Call rows.

    uv run python scripts/repair_prospect_call_ledger.py            # dry run
    uv run python scripts/repair_prospect_call_ledger.py --apply    # execute

Cleans up after two bugs, both fixed in code:

1. `_status_for` treated Retell's `not_connected` (an unanswered dial) as a live call, so
   those rows sat at status="in_progress" forever, `_fanout_post_call` never ran, and the
   prospect stayed "not_called" despite a visible call_count — companies that had plainly
   been called showed up under the dashboard's "Not called" section. Step 1 reconciles
   every stale call against Retell, which now reaches a terminal verdict.

2. `record_call()` set outreach_status="reached" at DIAL time, so every number that rang
   out or hit voicemail wore a green "Reached" badge. Step 2 recomputes status and
   outreach_status from each prospect's full call history via resync_status_from_calls.

Step 2 only touches prospects that have at least one LINKED terminal call. A prospect
with no linked calls is left alone on purpose: 153 of the tenant's calls carry no
prospect_id (inbound/web calls, plus dashboard-placed ones the phone match never
resolved), and resyncing against an empty history would walk a genuinely-called prospect
back down to "not_called" — re-creating the very bug this repairs. Use
POST /api/prospects/sync-calls to link those first.

`--drop-phantom-counts` additionally zeroes call_count / last_called_at for prospects
that claim calls but have no Call row backing ANY of them (e.g. "London Roofing Ltd":
call_count=4, zero linked calls). Off by default — a phantom count is only phantom if
the calls truly aren't ours, so run the backfill first and this second.

Hits the SHARED Neon database — see RUN.md.
"""

import argparse
import asyncio
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from backend.database import AsyncSessionLocal  # noqa: E402
from backend.models.call import Call  # noqa: E402
from backend.models.prospect import Prospect  # noqa: E402
from backend.services import call_service, prospect_service  # noqa: E402
from backend.services.retell_adapter import RetellAdapter  # noqa: E402

DEMO_TENANT_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
_TERMINAL = ("resolved", "escalated", "failed")


async def run(tenant_id: uuid.UUID, apply: bool, drop_phantom_counts: bool) -> None:
    async with AsyncSessionLocal() as db:
        # 1. Unstick calls whose terminal webhook never landed (or landed as
        #    not_connected and was discarded). Retell is the authority.
        stale = (
            (
                await db.execute(
                    select(Call).where(
                        Call.tenant_id == tenant_id,
                        Call.status == "in_progress",
                        Call.external_id.is_not(None),
                    )
                )
            )
            .scalars()
            .all()
        )
        print(f"step 1: {len(stale)} call(s) stuck at in_progress")
        if apply:
            updated = await call_service.reconcile_stale_calls(db, tenant_id, RetellAdapter())
            print(f"        reconciled {updated}")
        else:
            adapter = RetellAdapter()
            for call in stale:
                try:
                    payload = await adapter.get_call(call.external_id)
                except Exception as exc:  # noqa: BLE001 — dry run, keep going
                    print(f"        {call.external_id}: unreachable ({exc})")
                    continue
                verdict = call_service._status_for(
                    str(payload.get("call_status") or ""), payload.get("disconnection_reason")
                )
                print(
                    f"        {call.external_id}: call_status="
                    f"{payload.get('call_status')} reason={payload.get('disconnection_reason')}"
                    f" -> {verdict or 'still live, leave alone'}"
                )

        # 2. Recompute status + outreach_status from each prospect's whole history.
        prospects = (
            (await db.execute(select(Prospect).where(Prospect.tenant_id == tenant_id)))
            .scalars()
            .all()
        )
        calls = (
            (await db.execute(select(Call).where(Call.tenant_id == tenant_id))).scalars().all()
        )
        by_prospect: dict[uuid.UUID, list[Call]] = {}
        for call in calls:
            if call.prospect_id:
                by_prospect.setdefault(call.prospect_id, []).append(call)

        print("\nstep 2: resync status/outreach_status from linked calls")
        changed = 0
        for prospect in prospects:
            linked = by_prospect.get(prospect.id, [])
            if not any(c.status in _TERMINAL for c in linked):
                continue  # no evidence — never guess against an empty history
            before = (prospect.status, prospect.outreach_status)
            await prospect_service.resync_status_from_calls(db, prospect, linked)
            after = (prospect.status, prospect.outreach_status)
            if before != after:
                changed += 1
                print(f"        {prospect.name[:38]:38} {before} -> {after}")
        print(f"        {changed} prospect(s) corrected")

        # 3. Optional: prospects claiming calls that have no Call row at all.
        phantom = [
            p for p in prospects if (p.call_count or 0) > 0 and not by_prospect.get(p.id)
        ]
        print(f"\nstep 3: {len(phantom)} prospect(s) with a call_count but zero Call rows")
        for p in phantom:
            print(f"        {p.name[:38]:38} call_count={p.call_count} last={p.last_called_at}")
            if drop_phantom_counts:
                p.call_count = 0
                p.last_called_at = None
                if p.status in ("not_called", "no_answer", "voicemail", "called", "flagged"):
                    p.status = "not_called"
                if p.outreach_status == "reached":
                    p.outreach_status = "not_reached"
        if phantom and not drop_phantom_counts:
            print("        (pass --drop-phantom-counts to clear these)")

        if apply:
            await db.commit()
            print("\ncommitted.")
        else:
            await db.rollback()
            print("\ndry run — nothing written. Re-run with --apply.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant-id", type=uuid.UUID, default=DEMO_TENANT_ID)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--drop-phantom-counts", action="store_true")
    args = parser.parse_args()
    asyncio.run(run(args.tenant_id, args.apply, args.drop_phantom_counts))


if __name__ == "__main__":
    main()
