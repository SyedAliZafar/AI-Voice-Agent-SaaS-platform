"""Emergency stop — hang up live calls right now.

Why this exists as a script and not just an API route: the moment you need it most is
when an agent is talking to a real person and saying something wrong, and there is a
decent chance the API server, worker, and tunnel are all down at that moment (that is
often *why* the call is misbehaving). This needs nothing but RETELL_API_KEY. It does not
touch the database, does not need a tunnel, and does not import the FastAPI app.

    uv run python scripts/kill_calls.py                 # list live calls, kill nothing
    uv run python scripts/kill_calls.py --all           # hang up every live call
    uv run python scripts/kill_calls.py --call-id cal_x # hang up one specific call

Listing is the default precisely because this is the panic button: the destructive form
has to be typed deliberately. "Live" means Retell's own `ongoing` or `registered` — the
latter is a call that is dialing but not yet answered, which is usually the one worth
killing fastest. This asks Retell rather than our `calls` table on purpose: a call whose
webhook never arrived is stuck at in_progress locally and a call that ended cleanly may
still read in_progress, so the database is not trustworthy for "what is live right now".

Afterwards the ordinary call_ended webhook (or `POST /api/calls/sync`) settles the local
rows; this script deliberately does not write to the database, so it can never be the
thing that fails while a call is still up.
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.services.retell_adapter import RetellAdapter  # noqa: E402


def _describe(call: dict) -> str:
    """One line per call, chosen for deciding *which* call to kill under pressure:
    who it's talking to and how long it's been going, not internal ids alone.
    """
    call_id = call.get("call_id", "?")
    status = call.get("call_status", "?")
    to_number = call.get("to_number") or call.get("from_number") or "?"
    started = call.get("start_timestamp")
    when = ""
    if started:
        # Retell sends epoch milliseconds.
        from datetime import UTC, datetime

        when = datetime.fromtimestamp(started / 1000, UTC).strftime(" started %H:%M:%SZ")
    return f"{call_id}  {status:<11} -> {to_number}{when}"


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--all", action="store_true", help="Hang up every live call")
    parser.add_argument("--call-id", help="Hang up one specific call by its Retell call id")
    args = parser.parse_args()

    adapter = RetellAdapter()

    # A specific id is handled without listing first: if the operator already knows which
    # call to kill, a list call is pure latency between them and the hangup — and it would
    # also make this fail for a call that listing somehow missed.
    if args.call_id:
        print(f"Hanging up {args.call_id} ...")
        await adapter.stop_call(args.call_id)
        print("Done.")
        return 0

    live = await adapter.list_live_calls()
    if not live:
        print("No live calls. Nothing to stop.")
        return 0

    print(f"{len(live)} live call(s):")
    for call in live:
        print("  " + _describe(call))

    if not args.all:
        print("\nNothing was stopped. Re-run with --all, or --call-id <id> for just one.")
        return 0

    print()
    failed = 0
    for call in live:
        call_id = call.get("call_id")
        if not call_id:
            continue
        try:
            await adapter.stop_call(call_id)
            print(f"  stopped {call_id}")
        except Exception as exc:
            # Keep going: one failure must not leave the remaining calls up, which is the
            # whole point of --all. Reported via exit code so a wrapper can tell.
            failed += 1
            print(f"  FAILED  {call_id}: {exc!r}")

    print(f"\nStopped {len(live) - failed} of {len(live)}.")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
