"""One-time setup: import your Twilio number into Retell so agents can place
outbound test calls from it (see backend/services/test_call_service.py).

Usage:
    uv run python scripts/setup_retell_number.py

Reads TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN / RETELL_API_KEY from .env via
backend.config.get_settings(). Requires TWILIO_ACCOUNT_SID's phone number to
already exist in your Twilio account.

What it does:
  1. Looks up your Twilio number(s) and confirms Voice capability.
  2. Imports the number into Retell (POST /import-phone-number).
  3. Prints the number to paste into .env as RETELL_FROM_NUMBER, plus a
     reminder to enable international/Germany geo-permissions before dialing.

This is deliberately a standalone script, not an API endpoint — it's a rare,
one-time operation, not something the app needs on its hot path.
"""

import asyncio
import sys
from pathlib import Path

# Running this file directly (`uv run python scripts/setup_retell_number.py`) puts
# scripts/ on sys.path, not the repo root — so the local `backend` package can't be
# imported without this. (Not needed when running as `-m`, but the direct form is
# what's documented below and what people actually type.)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402

from backend.config import get_settings  # noqa: E402
from backend.services.retell_adapter import RetellAdapter  # noqa: E402


async def find_voice_capable_number(sid: str, token: str) -> str | None:
    url = f"https://api.twilio.com/2010-04-01/Accounts/{sid}/IncomingPhoneNumbers.json"
    async with httpx.AsyncClient() as client:
        resp = await client.get(url, auth=(sid, token))
        resp.raise_for_status()
        numbers = resp.json().get("incoming_phone_numbers", [])

    for entry in numbers:
        if entry.get("capabilities", {}).get("voice"):
            return entry["phone_number"]
    return None


async def main() -> int:
    settings = get_settings()

    if not settings.twilio_account_sid or not settings.twilio_auth_token:
        print("ERROR: TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN must be set in .env", file=sys.stderr)
        return 1
    if not settings.retell_api_key:
        print("ERROR: RETELL_API_KEY must be set in .env", file=sys.stderr)
        return 1

    print("Looking up Twilio numbers...")
    try:
        number = await find_voice_capable_number(
            settings.twilio_account_sid, settings.twilio_auth_token
        )
    except httpx.HTTPStatusError as exc:
        print(f"ERROR: Twilio API call failed: {exc}", file=sys.stderr)
        return 1

    if not number:
        print(
            "ERROR: No Voice-capable number found on this Twilio account.\n"
            "Check Twilio Console → Phone Numbers → your number → Capabilities shows 'Voice'.",
            file=sys.stderr,
        )
        return 1

    print(f"Found Voice-capable number: {number}")
    print("Importing into Retell...")

    adapter = RetellAdapter()
    try:
        await adapter.import_twilio_number(
            number, settings.twilio_account_sid, settings.twilio_auth_token
        )
    except httpx.HTTPStatusError as exc:
        print(f"ERROR: Retell import failed: {exc.response.text}", file=sys.stderr)
        return 1

    print()
    print("✓ Imported successfully.")
    print()
    print(f"Set this in .env:  RETELL_FROM_NUMBER={number}")
    print()
    print(
        "REMINDER — your test destination is Germany (+49):\n"
        "  1. Twilio Console → Voice → Settings → Geographic Permissions → enable Germany.\n"
        "  2. Confirm outbound international calling is enabled in your Retell account.\n"
        "Without both, the outbound call will be blocked or silently fail."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
