# Outliers — unresolved findings

Things found during real-call verification of ADR-009 (streaming + barge-in, phase4.md
Session 5, 2026-08-05) that are real but out of scope for that work. Not fixed here.

Status per finding, precisely: only §2 reflects an explicit user decision ("accept this
unit level, but put this in outliers.md" — 2026-08-05) to stop chasing a real-call repro
in favor of the existing unit tests. §1 and §3 are findings logged on the assistant's own
initiative during that same testing — the user has not yet said whether/when to fix them.
Don't describe §1 or §3 as "deferred by the user" — they're unresolved, full stop.

---

## 1. The completed-tool-call ledger is advisory, not enforced — real double-booking happened [CODE FIX SHIPPED 2026-08-05, VERIFIED ON A REAL CALL 2026-08-06]

**Verified on a real call, 2026-08-06.** Reproduced the original failure condition
directly: called, asked to book tomorrow 10am, then talked over the agent's own
confirmation with an ambiguous follow-up ("Ten... AM, right?") — same pattern as the
original transcript below. Result, checked against the `CallEvent` trail and Cal.com's
own API directly (not the agent's claim): exactly one `dispatched`/`result` pair for
`book_appointment` (confirmation `23450049`); the follow-up turn produced a
`skipped_duplicate` event instead of a second dispatch; the agent's spoken response used
"already done" framing ("Your appointment is confirmed for tomorrow at 10 AM") rather
than re-attempting; Cal.com's own booking list showed exactly one booking for that slot,
id matching the `CallEvent` exactly. A parallel clean-path control call (no ambiguity)
booked normally with no false positive from the duplicate checker. Full session
transcript/data not reproduced here — this file only tracks findings, not verification
logs.

**Update:** enforced in code now, at the user's explicit direction. `llm_service._execute_tool_calls`
takes a `check_duplicate(tool, arguments) -> synthetic_result | None` callback, consulted
*before* every side-effecting dispatch — `retell_ws.py` wires it to
`_find_duplicate_ledger_entry`, which matches against `completed_tool_calls` using the
same identifying-argument normalization `_ledger_entry` used to store it
(`_ledger_args_key`, shared so the two sides can't drift). A match skips the real handler
entirely and feeds the LLM `_duplicate_tool_result(tool, entry)` instead — which
deliberately gives the model something to *say* ("tell the caller it's already done"),
not just a prohibition, addressing the second half of the diagnosis below. See CONTEXT.md
ADR-009 §4c's 2026-08-05 update for the full writeup, and phase4.md Session 8 (marked
`[PARTIAL]`) for how this relates to that session's original, broader scope.

**Not done:** this is a unit-tested code path (`tests/test_retell_ws.py`), not yet
exercised on a real call the way the original bug was found — the original diagnosis
below came from a live call, and the fix hasn't had the same treatment. Also still open:
idempotency keys in `integration_service` (see the original fix-directions below) — this
check only catches a repeat our own process observed; it can't help across a process
restart.

**Original diagnosis, 2026-08-05 (kept verbatim for the record):**

**What happened:** A real test call (`call_ed92910aa6342a9c81ddb98c2ff`, 2026-08-05) asked
to book an appointment. Sequence of `book_appointment` dispatches, by `response_id`:

| response_id | start_time requested | outcome |
|---|---|---|
| 5 | 09:00 | rejected — collided with an earlier probe booking |
| 9 | 16:00 | **booked** — confirmation `23401802` |
| 10 | 16:00 (again) | rejected by Cal.com: "already has booking at this time" |
| 11 | 16:30 | **booked** — confirmation `23401815` |

Turn 10 happened as a completely normal, sequential next turn — no barge-in, no
cancellation, nothing anomalous in the task/event data. The model simply re-dispatched
`book_appointment` for the exact slot it had just successfully booked and already spoken
a confirmation for. Cal.com's own conflict check caught that specific repeat (good — real
backstop working). But instead of stopping there, the model treated the rejection as "try
a nearby time" and booked 16:30 too. **Net result: two real confirmed bookings for what
was clearly meant to be one appointment**, with no code-level check that would have
stopped it.

**Why this exists:** `retell_ws.py`'s `completed_tool_calls` ledger (ADR-009 §4c,
`_ledger_note`) is a system-prompt hint — "Already completed on this call — do NOT repeat
these" — injected into `conversation_history` each turn. It is *advisory only*: nothing
in code checks the ledger before letting a tool dispatch through. A model that decides
(for whatever conversational reason) to call the tool again anyway isn't stopped. The
ledger was built to survive *barge-in cancellation* specifically (ADR-009 §4c's own scope
note: "closes the caller-facing harm... is not a substitute for real idempotency keys in
integration_service") — this incident shows the same gap fires under completely ordinary
conversation flow too, not just barge-in.

**The injected ledger message, verbatim.** Reconstructed by tracing `_ledger_entry`/
`_ledger_note` in `retell_ws.py` against the real `dispatched`/`result` payloads for
`response_id=9` (`args: {start_time: "2026-08-06T16:00:00", attendee_email:
"ali@gmail.com"}`, `result: {confirmation_id: 23401802}`) — this is exactly what
`conversation_history[0]` contained for `response_id=10`'s turn:

```json
{
  "role": "system",
  "content": "Already completed on this call — do NOT repeat these:\n- book_appointment(start_time=2026-08-06T16:00:00, attendee_email=ali@gmail.com) -> 23401802"
}
```

**The real transcript** (from `transcripts.turns` for this call) around the re-dispatch:

```
caller: "Four. "
agent:  "Your appointment "
caller: "At "
agent:  "is booked for "
caller: "four PM? "
agent:  "Let me just confirm and book that four PM appointment for you.
         That four PM time is already taken. Could you pick a different time?"
```

**Why the model didn't treat the new request as already covered.** Not insufficient
identifying detail — `start_time=2026-08-06T16:00:00` is the exact slot, unambiguous, not
a phrasing mismatch. What the transcript shows instead: the caller talking over the
agent's own TTS mid-confirmation, landing on "four PM?" — genuinely ambiguous between
"did you say 4pm?" and "please book 4pm." The model's own generated text, *"Let me just
confirm and **book** that four PM appointment for you,"* shows which reading it picked: a
fresh instruction, not a callback to the ledger entry. The ledger note is purely negative
("do NOT repeat these") with no alternative action offered — it never tells the model
what to *say* when a matching request comes back. Faced with what sounded like a live
ask, the model prioritized being responsive over the constraint.

**Fix directions (first one now done, see the update at the top of this section):**
- ~~Enforce the ledger in code, not just the prompt: before `_execute_tool_calls`
  dispatches a tracked tool (`book_appointment`, `create_lead`, `send_sms`), check
  `completed_tool_calls` for a matching `(tool, start_time, attendee_email)` and either
  refuse to dispatch or require an explicit re-confirmation turn.~~ Done 2026-08-05.
- This is close to phase4.md Session 8 ("server-enforced confirmation gating") — the
  duplicate-check slice above is now part of that session (marked `[PARTIAL]`); the
  broader "confirm before a *first* attempt" scope is still open.
- Real fix for the underlying category of problem is idempotency keys in
  `integration_service.book_calendar_slot` (Cal.com v2 doesn't appear to support a
  client-supplied idempotency key on `/v2/bookings`; would need investigating — don't
  assume, verify against the actual API like the v1→v2 migration required).

**Cleanup needed:** delete Cal.com bookings `23401802` (Aug 6, 16:00) and `23401815`
(Aug 6, 16:30) — both fake, from this test.

---

## 2. The barge-in-during-tool-call scenario is still unproven end-to-end on a real call

Two real-call attempts (2026-08-05) never actually landed an interruption while
`book_appointment`'s Cal.com POST was in flight — both times, turns ran fully
sequentially with no task cancellation anywhere in the `CallEvent` trail. The tool call's
real HTTP round-trip is short (~0.5-2.3s observed), which makes timing an interruption by
ear against a live phone call genuinely hard.

**Decision (2026-08-05):** accepted the unit-level proof
(`tests/test_llm_service.py::TestToolCallShielding`, which deterministically exercises
cancellation mid-tool-call via a slow mock handler) as sufficient verification of the
shielding *mechanism* itself, rather than continuing to spend real Cal.com bookings
chasing a hard-to-time real-world repro. If real-call reproduction matters later, worth
revisiting with a deliberately slow-to-execute tool (e.g. a temporary artificial delay in
`book_calendar_slot`) to widen the interruption window rather than relying on Cal.com's
real (fast) latency.

---

## 3. The agent told the caller a slot was unavailable without ever checking [CODE FIX SHIPPED 2026-08-06, NOT YET VERIFIED ON A REAL CALL]

**Update:** the missing capability now exists. `check_availability`
(`backend/tools/check_availability.py` → `integration_service.check_calendar_availability`)
is a read-only tool backed by Cal.com's `GET /v2/slots`, returning
`{available, requested_time}` plus up to three closest same-day `nearby_alternatives`
when the requested time is taken — so the agent can offer another time instead of making
the caller guess. Endpoint verified three ways before coding (search → official doc →
live GET against the real event type, confirming it excludes already-booked times and
includes genuinely free ones), per the standing rule from the v1→v2 migration not to
assume an API shape. Note `/v2/slots` uses `cal-api-version: 2024-09-04`, deliberately
*different* from `/v2/bookings`' `2026-02-25` — each v2 sub-resource is versioned
independently; `SLOTS_API_VERSION` and `CAL_API_VERSION` must not be merged.

With the capability real, the agent's `system_prompt` now carries an `[AVAILABILITY]`
block requiring a `check_availability` call before ever asserting a time is free or
taken — an instruction that would have been unfair to give before, since nothing could
comply with it.

Deliberately NOT added to the ADR-009 §4c completed-tool-call ledger: this is a read,
and unlike the other reads it's one where *repeating* is actively correct, since a slot
can be taken by someone else mid-call.

**Not done:** unit-tested only (`tests/test_tools/test_check_availability.py`,
`tests/test_integration_service.py::TestCheckCalendarAvailability`) — not yet exercised
on a real call the way the original bug was found. The verification that matters: confirm
a `check_availability` dispatch appears in the `CallEvent` trail *before* any
`book_appointment`, and that the agent only calls a time unavailable after a check
returned `available: false` — not on its own say-so.

**Original diagnosis, 2026-08-05 (kept verbatim for the record):**

**What happened:** Same call (`call_ed92910aa6342a9c81ddb98c2ff`). The caller asked for
2pm; the agent replied *"Two PM tomorrow isn't available either. Would you like to try a
different time?"* — and **no `book_appointment` dispatch for 14:00 exists anywhere in the
event trail.** The turn at `10:25:29.957671` has a single `llm_timing` row with
`stage: "initial"` and no `tool_followup` companion (compare every tool-calling turn in
that call, which has both at a shared timestamp): a text-only turn, zero tool calls. The
next dispatch is at `10:25:37`, and it's for 16:00.

So the agent fabricated an availability claim. It happened to be *correct* — earlier
direct probing of Cal.com confirmed 14:00 Berlin really was unavailable — which is
precisely what makes it dangerous: a fabrication that lands right looks like the system
working.

This is the same category as phase4.md Session 1 ("Stop the lying" — `transfer_call` and
`send_sms` returning hardcoded `{"success": True}`). Telling a caller a time is
unavailable when nothing checked is a trust problem whether or not the guess is lucky.

**The structural cause, which is the more interesting half:** there is no availability
tool. `backend/tools/__init__.py` registers `book_appointment`, `lookup_customer`,
`create_lead`, `transfer_call`, `send_sms` — nothing that answers "is this slot free?".
The only way for the agent to find out is to *attempt a booking and see if it fails*. So
the model is structurally cornered into either blind-attempting bookings (which is how
the duplicate in §1 above happened) or guessing (which is what it did here). Neither is
acceptable, and no amount of prompt tuning fixes the absence of the capability.

**Fix directions (both now done — see the update at the top of this section):**
- ~~Add a `check_availability` tool backed by Cal.com's slots/availability API, so
  "is 2pm free?" is answerable without a write. **Verify the endpoint before coding it** —
  a guess at `GET /v2/slots` returned 404 during probing on 2026-08-05, so the real v2
  path/params need looking up properly.~~ Done 2026-08-06. Footnote on that 404: the
  path was right all along — the failure was a *missing/incorrect* `cal-api-version`
  header, not a wrong URL. Another instance of the same lesson: the error a wrong guess
  produces can point at the wrong cause.
- ~~Once that exists, the system prompt can legitimately require checking before
  asserting availability.~~ Done 2026-08-06 (`[AVAILABILITY]` block).
- Still open, lower priority: `check_availability` answers for a *single* requested time
  on a single day. A caller asking an open-ended "when are you free this week?" would
  still have to be met with repeated single-time checks. A range/summary mode would be a
  separate, larger change.

---

## 4. Bad-email dispatches reached Cal.com before being caught, instead of before dispatch [LOWER SEVERITY — nothing unsafe happened]

**What happened:** During the 2026-08-06 real-call verification of §1's fix (Call B, the
clean-path control), `attendee_email` went through two failed `book_appointment`
dispatches before landing on a valid address on the third try — real STT misfires on
"Ali at the rate gmail.com":

| attempt | `attendee_email` | outcome |
|---|---|---|
| 1 | `""` (empty) | Cal.com 400 — no contact method |
| 2 | `"aliatrategmail.com"` (no `@`) | Cal.com 400 — invalid email |
| 3 | `"ali@gmail.com"` | booked |

**Why this is lower severity, not a bug to chase:** both bad attempts were correctly
rejected by Cal.com's own validation — no booking was ever created with bad data, and
nothing needed the duplicate-check fix from §1 to save it. The duplicate checker itself
handled this correctly too, worth noting as the negative-test-case proof for §1's fix:
each attempt had a genuinely different `attendee_email`, so `_find_duplicate_ledger_entry`
correctly treated all three as distinct requests rather than false-flagging the retries
as repeats of something already done.

**The actual gap:** a basic email format check before dispatch (not after Cal.com rejects
it) would save a round-trip per bad attempt and reduce caller-facing friction — two full
turns of "let me try that again" instead of the model catching an obviously malformed
address itself. Not scoping a session for this now; recorded so it doesn't get lost.
