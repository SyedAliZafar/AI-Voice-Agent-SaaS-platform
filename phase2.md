# Phase 2 — Outbound Test Call: from-number setup

Status: **resolved and verified end-to-end.** This picks up right after the Agent Builder +
`/agents/{id}/test-call` endpoint (see `CONTEXT.md` for architecture,
`backend/services/test_call_service.py` for the call-placement logic).

> **Decision (superseding the "two ways forward" below): take Option A.**
> The SIP-trunk credential bug described under "Root cause" has since been *fixed* in code
> (see "Resolution" at the bottom), so Option B now works — but it still requires manual
> Twilio Console trunk setup for no benefit over simply buying a number inside Retell.
> Option A is the path; Option B is kept working and documented as a fallback for anyone
> who later needs to keep an existing Twilio number.

## What happened

Running the setup script:
```
uv run python scripts/setup_retell_number.py
```

**Bug #1 (fixed):** `ModuleNotFoundError: No module named 'backend'`. Running a script file
directly (`python scripts/setup_retell_number.py`) puts `scripts/` on `sys.path`, not the repo
root, so the local `backend` package wasn't importable. Fixed in
[scripts/setup_retell_number.py](scripts/setup_retell_number.py) by inserting the repo root onto
`sys.path` before the `backend` imports.

**Bug #2 (real, still open):** after the fix, the script correctly found the Twilio number
(`+12526233516`, Voice-capable) but Retell rejected the import:
```
ERROR: Retell import failed: {"status":"error","message":"Internal Server Error"}
```

### Root cause

`RetellAdapter.import_twilio_number()` (in
[backend/services/retell_adapter.py](backend/services/retell_adapter.py)) sends the raw Twilio
**Account SID / Auth Token** as `sip_trunk_auth_username` / `sip_trunk_auth_password`. That's
wrong — Retell's `/import-phone-number` endpoint expects credentials for a **Twilio Elastic SIP
Trunk** pointed at Retell's SIP domain, not your Twilio account API credentials. Those are two
different credential types:
- Account SID/Token → authenticates *API calls* to Twilio.
- SIP trunk username/password → a credential list *you* create inside a Twilio Elastic SIP
  Trunk, used for SIP call authentication between Twilio and Retell.

There is no way to script the trunk creation itself — it requires a few clicks in the Twilio
Console (or a Twilio API call using different, trunk-specific endpoints we haven't built).

## Two ways forward

### Option A — Buy a number directly inside Retell (recommended for testing)
Skips Twilio entirely for this number. Simpler, no SIP trunk, and it's what most people do just
to hear a script.
1. Retell dashboard → Phone Numbers → Buy a number (~$2–3/mo, US number typically instant).
2. Set `RETELL_FROM_NUMBER=<that number>` in `.env`.
3. Delete/skip the Twilio-import step — `scripts/setup_retell_number.py` and
   `RetellAdapter.import_twilio_number()` become unnecessary for this path.
4. Done — the existing `/agents/{id}/test-call` endpoint works unchanged (it only reads
   `RETELL_FROM_NUMBER`, doesn't care how it was provisioned).

### Option B — Actually import the existing Twilio number
Keeps using the Twilio number already in `.env`, but requires manual Twilio Console setup first:
1. Twilio Console → Elastic SIP Trunking → Create a new Trunk.
2. **Origination**: add an Origination URI pointing at Retell's SIP domain
   (`sip:5t4n6j0wnrl.sip.livekit.cloud` or whatever Retell's current docs specify — check
   Retell's "Import Twilio Number" guide for the exact domain, it may have changed).
3. **Credential List**: under the trunk, create a new Credential List with a username/password
   *you choose* (not your Twilio Account SID/Token) — this is what SIP auth actually uses.
4. Assign your existing Twilio number to this trunk (Numbers tab on the trunk).
5. Update `RetellAdapter.import_twilio_number()` to send that trunk's **termination URI** +
   the **credential list username/password** you created in step 3 — not
   `settings.twilio_account_sid` / `settings.twilio_auth_token`. Likely needs two new
   settings, e.g. `retell_sip_trunk_username` / `retell_sip_trunk_password`, or accept them
   as CLI args to the setup script instead of reading from `.env` (they're a one-time input,
   not an ongoing secret the app needs at runtime).
6. Re-run `scripts/setup_retell_number.py` with the corrected payload.

**Recommendation:** do **Option A** first to unblock hearing the pitch today (this is what the
"test call" feature is for — proving out the script, not proving out telephony infra). Revisit
Option B later only if there's a real reason to keep using the existing Twilio number long-term
(e.g. it's already the number customers call back, or Twilio's per-minute rates matter at scale).

## Once a from-number exists (either path)

Unblocked — no further code changes needed:
1. `RETELL_FROM_NUMBER=<number>` in `.env`; restart the API.
2. Twilio Console → Voice → Settings → Geographic Permissions → enable **Germany** (destination
   confirmed by the user). Confirm outbound international is allowed in Retell too.
3. Open a Retell-platform agent → **Test call** card → enter your E.164 number → **Call me**.

## Verified end-to-end

Bought a Retell number (`+14059146006`), set `RETELL_FROM_NUMBER`, recreated the API
container so it picked up the new `.env` value (`docker compose restart` alone does not —
use `docker compose up -d api`), then called `POST /api/agents/{id}/test-call` against the
existing "Ali" agent. **The phone rang and Retell spoke the agent's `system_prompt`.** No
code changes were needed for this — as predicted, it was a pure live-call smoke test.

Note what this does and doesn't prove: it confirms the telephony leg (Twilio number →
Retell → ringing phone with audio) works. It does not exercise DeepSeek or any server-side
tool — this endpoint intentionally runs on Retell's own hosted LLM instead (see
`test_call_service.py`'s docstring). See `phase0.md` for what comes next.

## Resolution — the SIP-trunk bug is fixed (Option B now works, but is not the chosen path)

`RetellAdapter.import_twilio_number()` was sending two wrong things: an empty
`termination_uri`, and the Twilio **Account SID/Auth Token** in the
`sip_trunk_auth_username`/`sip_trunk_auth_password` fields. Retell's
`/import-phone-number` needs the trunk's termination URI plus credentials from a
**Credential List** created inside the Twilio Elastic SIP Trunk — a different credential
type entirely. That mismatch is what produced the opaque
`{"status":"error","message":"Internal Server Error"}`.

Fixed by threading three real values through, backed by new settings in `backend/config.py`
(`twilio_termination_uri`, `retell_sip_trunk_username`, `retell_sip_trunk_password`):

- `backend/services/retell_adapter.py` — `import_twilio_number(number, termination_uri,
  sip_trunk_username, sip_trunk_password)`; no longer takes the Twilio API credentials.
- `backend/services/voice_platform.py` — base signature updated to match.
- `scripts/setup_retell_number.py` — validates all three are set and prints the exact
  Twilio Console steps if they aren't. The Twilio SID/token are still read, but only to
  *look up* the number via the Twilio REST API.

These fields map 1:1 to Retell's own "Connect to your number via SIP trunking" dialog
(Phone Number / Termination URI / SIP Trunk User Name / SIP Trunk Password).

**This code is kept but is not on the critical path.** Option A (buy a Retell number)
requires none of it. Only return to `setup_retell_number.py` if there's a concrete reason
to keep using the existing Twilio number `+12526233516`.

## Superseded by
The larger architectural direction has moved on — see the Phase 0 plan (de-risking before
the Retell Custom LLM WebSocket migration). Getting a phone to ring on this hosted-LLM path
is Task 1 of that plan: it is the baseline the WebSocket work will be compared against, and
the hosted-LLM path stays working as the fallback throughout that migration.
