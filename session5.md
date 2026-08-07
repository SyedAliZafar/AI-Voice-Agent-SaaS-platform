# Session 5 handoff — cancel/reschedule tools + timeout honesty fix

Written 2026-08-06 so a fresh Claude session can pick this up cold, with the same
context this session had. Read this first; it points at the deeper writeups
(`outliers.md`, `CONTEXT.md` ADR-009 §4c) rather than repeating them in full.

## Where this fits

This is the 3rd piece of work in a running series, all discovered via **real phone
calls**, not just unit tests, against this repo's Retell + DeepSeek + Cal.com stack:

1. ADR-009 (streaming + barge-in cancellation) — `phase4.md` Session 5. Done, verified.
2. `check_availability` tool — `outliers.md` §3. Done, verified.
3. **This session**: `cancel_appointment`/`reschedule_appointment` tools — `outliers.md`
   §5 — plus two more bugs (§6) found while verifying §5 on a real call.

The pattern every time: build the fix, **verify the real third-party API contract
empirically before coding against it** (this project has been burned repeatedly
assuming Cal.com API shapes — v1 was silently decommissioned, `/v2/slots` 404'd on a
missing header, `cancellationReason` turned out not to be optional despite the docs),
then place a **real test call** and check the `CallEvent` audit trail and Cal.com's
actual state directly — never trust the transcript or the agent's own claims.

## What was done, in order

### 1. `cancel_appointment` / `reschedule_appointment` tools (outliers.md §5)

**The bug this fixes:** a real call had the caller ask to reschedule a booking; the
agent said *"let me cancel the nine AM"* — but no cancel/reschedule tool existed at
all. The model fabricated an action, not just a fact, leaving the caller with two real
bookings while believing they had one.

**Built:**
- `backend/services/integration_service.py` — `cancel_calendar_booking`,
  `reschedule_calendar_booking`. `POST /v2/bookings/{bookingUid}/cancel` and
  `.../reschedule`, both on Cal.com's string `uid` (never the numeric `id`), both on
  `CAL_API_VERSION` (`2026-02-25`, same as booking creation — confirmed independently,
  NOT `SLOTS_API_VERSION`).
- `backend/tools/cancel_appointment.py`, `reschedule_appointment.py` — new tools,
  registered in `backend/tools/__init__.py`.
- `backend/tools/book_appointment.py` — fixed to capture and return `booking_uid`
  (Cal.com's string uid) alongside the existing numeric `confirmation_id`, which it
  previously discarded entirely. Cancel/reschedule need exactly the field that was being
  thrown away.
- `backend/api/retell_ws.py` ADR-009 §4c ledger extended: `_LEDGER_ARG_KEYS` gained
  `cancel_appointment`/`reschedule_appointment` (keyed on `booking_uid`);
  `_LEDGER_EXTRA_RESULT_KEYS` (new) lets a ledger entry carry a second field
  (`booking_uid`) beyond the existing `result_id`, rendered inline in the ledger note as
  `[booking_uid=...]` so the model can read a booking's uid back out of context it
  already sees every turn — no new backend lookup logic needed.
- **Two tools, not one**, deliberately mirroring Cal.com's own two atomic endpoints —
  a merged tool that composed "cancel, then book_appointment again" would reintroduce a
  real race (cancel succeeds, rebooking fails, caller loses the appointment entirely).

**Real API research done before coding** (see `outliers.md` §5 and the plan file
`C:\Users\aliz\.claude\plans\our-retell-ws-py-custom-llm-handler-vectorized-knuth.md`
for the full trail): cancelled a real leftover booking to confirm the cancel response
shape live; ran a throwaway book→reschedule→cancel probe which confirmed an important,
easy-to-miss contract detail — **a successful reschedule returns a NEW `uid`, not the
one sent in** (Cal.com supersedes the original booking; the new one carries
`rescheduledFromUid` back to the old one). The uid-rotation risk self-resolves in the
ledger design without special-casing: a reschedule is its own ledger entry keyed on the
*old* uid, carrying the *new* uid in `extras`.

**System prompt** (the test agent's own `Agent.system_prompt`, not
`retell_ws._system_prompt_with_context`'s generic per-turn block — see below): a
`[CANCELLING OR RESCHEDULING]` section requiring the tools be called before ever
claiming an action happened, that `booking_uid` come from the ledger note only, never
invented.

**Verified on a real call** (`call_e28e21214404ebb3054eeb9eb7a`, 2026-08-06). The core
fix held on the case that matters most: asked to cancel something from *before this
call*, the agent correctly refused rather than fabricate. Booked-then-rescheduled in the
same call correctly dispatched `reschedule_appointment`, not a second `book_appointment`.

### 2. Two more bugs found during that same verification call (outliers.md §6) — both fixed

**Bug #1 — `cancellationReason` isn't actually optional**, despite Cal.com's v2 docs
saying it is. A no-reason cancel attempt got a real `400: "Cancellation reason is
required"`. Fixed: `cancel_calendar_booking` now always sends a reason, defaulting to
`"Cancelled by caller"`.

**Bug #2 — more serious: a timeout got reported as a bare error, and the model claimed
success anyway.** A `reschedule_appointment` dispatch timed out client-side (~20.1s,
matching the `timeout=20.0` client setting almost exactly), produced `{"error": ""}`,
and the model's next turn said *"Your appointment has been moved to 1:30 PM tomorrow."*
— a direct violation of the system prompt's existing "never claim success without tool
confirmation" instruction. **Checked directly against Cal.com: it had actually worked**
(the old booking was cancelled, a new one existed at the new time) — but only by luck,
since Cal.com kept processing the request after the client gave up waiting. The same
timeout on a genuinely failed request would have produced an identical false claim.

Fixed in code, not just the prompt (the prompt instruction already existed and didn't
hold on its own):
- `integration_service.IntegrationTimeoutError(IntegrationError)` — new distinct
  exception, raised when `httpx.TimeoutException` interrupts the POST in
  `book_calendar_slot`, `cancel_calendar_booking`, AND `reschedule_calendar_booking`
  (applied to all three — nothing about the ambiguity is reschedule-specific).
- `backend/tools/base.py` — new shared `uncertain_result(action)` helper. Each of the
  three tool handlers now catches `IntegrationTimeoutError` and returns
  `{"status": "uncertain", "instruction": "..."}` instead of letting the exception
  propagate as a bare `{"error": ...}`. Deliberately not error-shaped, so the
  distinction survives at a glance in the `CallEvent` audit trail, not just in prose the
  model has to parse correctly mid-call.
- `retell_ws._ledger_entry` returns `None` for a `status: "uncertain"` result — an
  unconfirmed outcome must not be recorded as "already done," and a genuine retry must
  not be blocked as a false duplicate.

**Explicitly not done, by deliberate choice under time budget** (see `outliers.md` §6's
closing note): a smarter fix would reconcile an unconfirmed timeout with a follow-up
read (e.g. `GET` the booking by `uid` after a `cancel_appointment` timeout to actually
resolve what happened) instead of just hedging. Not implemented — that's another
unverified Cal.com endpoint shape, and `reschedule_appointment`'s version of the same
idea is harder (the new uid isn't discoverable without a further, undocumented lookup).
Worth revisiting if the "I'll follow up" hedge turns out to fire often in practice.

### 3. Tests, lint, types

248 tests passing at the end of this session, `ruff check .` clean, `mypy backend`
at the same 7-error pre-existing baseline (unrelated: celery/jose missing stubs,
tenant.py/agent.py forward-ref timing, rate_limit.py Address|None, two llm_service.py
`create()` overload mismatches — none in any file this session touched). New/changed
test files: `tests/test_integration_service.py` (timeout tests for all three mutating
functions, corrected default-reason assertion, new `TestCancelCalendarBooking`/
`TestRescheduleCalendarBooking` classes), `tests/test_tools/test_base.py` (new),
`test_cancel_appointment.py` (new), `test_reschedule_appointment.py` (new),
`test_book_appointment.py` (updated for `booking_uid`), `tests/test_retell_ws.py`
(ledger extension tests, uncertain-result exclusion test).

### 4. Docs

`outliers.md` — §1 and §3 marked verified-on-a-real-call (were previously "shipped, not
yet verified"); §5 added, then marked verified with the two new bugs cross-referenced;
§6 added with full real evidence (`CallEvent` trail excerpt, the transcript quote, the
actual Cal.com booking IDs proving the reschedule really did land server-side despite
the timeout). `CONTEXT.md` ADR-009 §4c has two dated addenda (the cancel/reschedule
capability, then the timeout-honesty fix). This file (`session5.md`) is new.

## Full outliers.md status (all findings, for a fast orientation)

| § | Finding | Status |
|---|---|---|
| 1 | Ledger was advisory-only, not enforced — real double-booking | Fixed + verified on a real call |
| 2 | Barge-in-during-tool-call unproven on a real call | User-accepted unit-level proof as sufficient (explicit decision, not deferred by default) |
| 3 | Agent fabricated an availability claim, never checked | Fixed (`check_availability`) + verified on a real call |
| 4 | STT email misfires reached Cal.com before validation | Logged, lower severity, not scoped — still open |
| 5 | Agent claimed a cancellation it had no tool to perform | Fixed (`cancel_appointment`/`reschedule_appointment`) + verified on a real call |
| 6 | That verification surfaced 2 more bugs (reason-required, timeout→false-success) | Both fixed this session; reason-required verified on a real call 2026-08-07 (see below), timeout→uncertain remains unit-verified only |

## What's left — pick up here

1. ~~**Real-call reverification of §6's two fixes specifically.**~~ **Done 2026-08-07**
   for the reproducible half. Bug #1 (default cancellation reason) verified on a real
   call (`call_1368a69c8f28ea4c9d8e140e610`): booked, then asked to cancel with no
   reason given; `CallEvent` trail shows `cancel_appointment` dispatched with no
   `reason` argument, result `cancelled: true`; checked directly against Cal.com's own
   API afterward — `status: "cancelled"`, `cancellationReason: "Cancelled by caller"`,
   the exact fallback value. Full detail in `outliers.md` §6. Bug #2 (timeout → uncertain
   result) is **still unit-verified only** — a real client-side timeout against Cal.com's
   normal (~1-4s observed) latency isn't reproducible on demand, exactly as anticipated
   here. This call's own `cancel_appointment` round-trip completed normally (~3.7s),
   which only confirms no regression on the ordinary path, not the uncertain-result path
   itself. If that matters more later, the way to actually force it is an artificial
   delay in `cancel_calendar_booking`/`reschedule_calendar_booking` for one test run
   (same idea outliers.md §2 suggested for barge-in timing) — not attempted here.
2. **§4 (STT email misfires)** — logged, not scoped, still open, lower severity.
3. **§6's own noted follow-up** — timeout reconciliation via a follow-up read (verify
   `GET /v2/bookings/{uid}` empirically first) instead of the current blanket
   "uncertain" hedge, if that hedge turns out to fire often in practice.
4. **Idempotency keys in `integration_service`** — noted as open since ADR-009 §4c's
   original writeup. The duplicate-check/ledger work reduces the caller-facing risk but
   doesn't replace real idempotency keys at the API layer.
5. **`check_availability`'s single-instant-only scope** — noted in §3 as lower priority:
   it answers "is this exact time free," not an open-ended "when are you free this
   week." A range/summary mode would be a separate, larger change.
6. Nothing is uncommitted-and-fragile — all changes are plain working-tree edits, no
   commits made this session (per this project's "only commit when asked" convention).
   `git status` will show the full diff list.

## Current live infra state (all ephemeral — expect to redo most of this)

This project's dev tunnel is a Cloudflare **quick tunnel**, which dies routinely (DNS
failure, or Cloudflare invalidating a tunnel left running too long) — expect to
recreate it almost every session. See `RUN.md` and `CONTEXT.md` ADR-007 for the full
story; short version:

```powershell
docker compose up -d --force-recreate tunnel-quick
docker compose logs tunnel-quick | Select-String "trycloudflare.com|protocol http2"
# put the printed URL in .env as PUBLIC_BASE_URL, then:
docker compose up -d --force-recreate api
uv run python scripts/check_custom_llm.py   # full green run before placing any real call
```

**The Postgres schema was found completely empty partway through this session**
(migrations never applied against whatever fresh volume was in play) — if
`check_custom_llm.py` fails with `relation "X" does not exist`, that's the cause, not a
code bug. Fix:
```powershell
uv run alembic -c backend/migrations/alembic.ini upgrade head
uv run python scripts/dev_token.py   # reseeds the demo tenant, prints a fresh bearer token
```

**As of the end of this session:**
- Test agent id: `c921a011-db4e-480c-97cc-880347d53659` — recreated fresh this session
  (the previous one, `07bf2deb-...`, was lost when the DB got wiped), `use_custom_llm`,
  `deepseek-chat`, full `[AVAILABILITY]` + `[CANCELLING OR RESCHEDULING]` system prompt
  already applied (see `agent_prompt.json` in the session scratchpad for the exact
  text, or just read `Agent.system_prompt` from the DB — it's live).
- Its `book_appointment` `ToolConfig` is seeded: `calendar_id=6553289`,
  `calendar_timezone=Europe/Berlin`, real `cal_live_...` API key (a live Cal.com
  account — every booking made against it during testing is real; clean up test
  bookings afterward, same as every prior session).
- `PUBLIC_BASE_URL` / bearer token as of last check were both fresh and working — do
  not assume either still is by the time you read this; verify with
  `scripts/check_custom_llm.py` before trusting them, per the standing rule of this
  whole series (verify, don't assume).
- One real leftover booking from this session's original incident, `23454719`
  (2026-08-07 11:15 Berlin), is still live/uncancelled — left deliberately, see
  `outliers.md` §5's cleanup note for why.

**2026-08-07 follow-up session:** started from a fully cold stack (no containers
running) and the `.env` `PUBLIC_BASE_URL` was already dead. Recreating `tunnel-quick`
once was NOT enough — it died again (Cloudflare returned "Unauthorized: Tunnel not
found") within the same session, between the infra green-check and actually placing
the call, requiring a second recreate/URL-swap/`api` restart before the real test call
would go through. Concrete new evidence for this project's existing "expect to
redo the tunnel almost every session, sometimes more than once" warning — not a new
failure mode, just a sharper data point on how often it bites. Test agent
`c921a011-...` and its `ToolConfig` survived this session's DB intact (no reseed
needed); the `[AVAILABILITY - NEVER GUESS]` header text doesn't literally contain the
substring `[AVAILABILITY]` (worth remembering if grepping the prompt programmatically
again). `PUBLIC_BASE_URL` as of the end of this session is whatever the *second*
`tunnel-quick` recreate printed — treat it as dead by default, same as always, and
re-verify with `check_custom_llm.py` first.

## Standing rules this series has established (apply them to whatever comes next)

- **Verify third-party API shapes empirically before coding against them.** Docs have
  been wrong or ambiguous multiple times (v1 deprecation, missing-header 404 misread as
  wrong URL, "optional" cancellationReason that wasn't). A throwaway real call/booking
  that gets cleaned up immediately after is cheap insurance.
- **Verify fixes on a real call, checking the `CallEvent` trail and the third-party
  system's own state directly** — never trust the transcript or what the agent claims
  it did.
- **Fix genuine bugs in code, not just prompt patches**, especially when a prompt
  instruction already existed and didn't hold (§6's core lesson).
- **Report findings and ask before scoping new work** — don't unilaterally decide
  what's in-scope-to-fix-now vs. log-for-later. This session's owner has been explicit
  and specific about which of several findings get fixed immediately vs. logged; don't
  assume authority to make that call by default.
- **Don't attribute deferral decisions to the user unless they explicitly made
  them** — several `outliers.md` entries are unresolved on the assistant's own
  initiative, not "deferred by the user." Keep that distinction precise going forward.
