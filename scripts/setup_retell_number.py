"""One-time setup: import your Twilio number into Retell so agents can place
outbound test calls from it (see backend/services/test_call_service.py).

NOT the recommended path — see phase2.md. Buying a number directly in the Retell
dashboard needs none of this (no SIP trunk, no Twilio Console setup) and is what
RETELL_FROM_NUMBER is normally set from. Use this script only if you specifically
need to keep dialing from an existing Twilio number.

Usage:
    uv run python scripts/setup_retell_number.py

Reads TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN / RETELL_API_KEY / TWILIO_TERMINATION_URI /
RETELL_SIP_TRUNK_USERNAME / RETELL_SIP_TRUNK_PASSWORD from .env via
backend.config.get_settings(). Requires TWILIO_ACCOUNT_SID's phone number to already
exist in your Twilio account, AND an Elastic SIP Trunk already set up in the Twilio
Console with that number assigned to it (see the TWILIO_TERMINATION_URI error message
below for the exact steps) — this script cannot create the trunk for you.

Note: TWILIO_ACCOUNT_SID/TWILIO_AUTH_TOKEN here are only used to look up your number via
the Twilio REST API. They are NOT the SIP trunk credentials Retell needs — those are a
separate username/password you create inside the trunk's Credential List
(RETELL_SIP_TRUNK_USERNAME/PASSWORD below).

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
    if not settings.twilio_termination_uri:
        print(
            "ERROR: TWILIO_TERMINATION_URI must be set in .env.\n"
            "Create an Elastic SIP Trunk in the Twilio Console (Elastic SIP Trunking →\n"
            "Trunks → Create new Trunk), add your number to it under 'Origination', and\n"
            "copy its trunk domain (looks like 'yourtrunk.pstn.twilio.com') into .env as\n"
            "TWILIO_TERMINATION_URI.",
            file=sys.stderr,
        )
        return 1
    if not settings.retell_sip_trunk_username or not settings.retell_sip_trunk_password:
        print(
            "ERROR: RETELL_SIP_TRUNK_USERNAME / RETELL_SIP_TRUNK_PASSWORD must be set in .env.\n"
            "These are NOT your Twilio account SID/token — they're a username/password *you\n"
            "choose* inside the trunk's Credential List (Twilio Console → your trunk →\n"
            "Authentication → Credential Lists → create one). Put the same values in .env.",
            file=sys.stderr,
        )
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
            number,
            settings.twilio_termination_uri,
            settings.retell_sip_trunk_username,
            settings.retell_sip_trunk_password,
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
