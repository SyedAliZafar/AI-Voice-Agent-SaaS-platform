# Prompts to test — pending real-call verification

Real phone calls can't be placed from inside a Claude Code session — they need the
user to actually dial. This file tracks work that's code-complete and unit-tested but
still needs a real-call pass before being called fully done, per this project's
standing rule: tests passing is not the same as verified (see phase4.md Session 5's
outliers.md findings — every real bug in that series was invisible to unit tests and
only surfaced on a real call).

When picking this file back up in a new Claude Code session: read the relevant section
below for full context (what changed, which files, why it matters), then walk the user
through placing the call and interpreting the CallEvent trail / transcript / Cal.com
state afterward — same pattern as Session 5's verification loop. Don't just ask "did it
sound right" — check the actual data.

---

## Session 7 — Filler audio during tool calls

**Status:** code complete, unit-tested (258 tests passing), not yet real-call verified.

**What changed:** When a tool call (e.g. `check_availability`, `book_appointment`)
takes longer than ~300ms, the agent now speaks a short filler phrase ("One moment...")
before the real answer, instead of leaving the caller in silence. Filler phrases are
pre-written text spoken by Retell's normal voice (not pre-recorded audio — Retell owns
TTS in this architecture, confirmed against ../../CONTEXT.md's no-custom-voice-synthesis
rule).

**Files touched:**
- `backend/services/llm_service.py` — `_start_tool_calls_shielded` (split out of
  `_run_tool_calls_shielded`), the `asyncio.wait(..., timeout=TOOL_CALL_FILLER_DELAY_SECONDS)`
  race in `stream_agent_response`, `TOOL_CALL_FILLER_DELAY_SECONDS = 0.3`,
  `_FILLER_PHRASES`, `_pick_filler_phrase()`.
- `tests/test_llm_service.py` — `TestStreamAgentResponse`: slow-tool-yields-filler,
  fast-tool-yields-none, cancellation-mid-filler-wait-still-completes-tool.
- `phase4.md` — Session 7 marked done.

**What to test on a real call:**
1. Trigger a slow lookup (`check_availability` or `book_appointment` against real
   Cal.com latency). Confirm the filler phrase actually plays and the transition to
   the real answer sounds natural, not jarring or robotic.
2. If two slow tool calls happen in one turn, listen for whether two fillers
   back-to-back sounds repetitive. This decides whether "cap at one filler per turn"
   (a flagged, not-yet-made judgment call) is worth doing.
3. Interrupt (barge-in) while the filler is playing. Confirm the underlying booking
   still completes correctly afterward — this exercises the same shielding protection
   from Session 5, which the implementation claims is unweakened but hasn't been
   proven live for this specific interaction.

**Why it matters if it fails:** Low severity compared to Session 5's findings — worst
case here is "sounds slightly awkward," not a double-booking or a lie to the caller.
Still worth confirming before calling this session closed, consistent with this
project's verification standard.

---

## Session 6 — Parallel tool dispatch (lightweight sanity check, optional)

**Status:** code complete, heavily unit-tested (concurrency proven via wall-clock
test, ordering guarantees tested under reversed completion order), not real-call
checked. Lower priority than Session 7 — flagging for completeness, not urgency.

**What changed:** `_execute_tool_calls` now dispatches multiple tool calls in a single
turn concurrently via `asyncio.gather`, instead of one at a time. A synchronous
planning pass runs all duplicate-ledger checks before any dispatch, so concurrent
calls can't race past the Session 5/8 ledger protection.

**Files touched:** `backend/services/llm_service.py` (`_execute_tool_calls`
rewritten into two phases), `tests/test_llm_service.py` (`TestConcurrentToolDispatch`,
4 tests).

**What to test on a real call:** Get the agent to legitimately fire two tools in one
turn (e.g. a booking that also creates a CRM lead, or `check_availability` +
`lookup_customer` back to back) and confirm both complete correctly with no ledger
confusion or CallEvent ordering weirdness in the trail.

---

## Session 8 — Server-enforced confirmation gating (not yet started)

**Status:** not yet scoped as a session — the original phase4.md ask needs
clarification against what Session 5 already partially covers before writing a
build prompt.

**Context for whoever picks this up:** Session 5 (via outliers.md §1) already built a
form of confirmation gating — the `completed_tool_calls` ledger blocks a *repeat*
dispatch of something already completed (`book_appointment`, `create_lead`,
`book_discovery_call` are all covered, keyed via `_LEDGER_ARG_KEYS` in
`retell_ws.py`). What phase4.md Session 8 originally asked for is broader: requiring
the caller to actually confirm before a side-effecting tool fires for the *first*
time, not just blocking re-dispatch of something already done.

**Before building anything:** ask Claude Code to explicitly map which part of the
original Session 8 ask is already covered by the Session 5 ledger work, and which
part (first-attempt confirmation) is still genuinely open, so nothing gets rebuilt
that already exists.

---

## How to add a new entry

When a session finishes and needs real-call verification, add a section here with:
`Status`, `What changed` (in plain terms + technical), `Files touched`, `What to
test on a real call` (concrete steps, what evidence to check — CallEvent trail,
Cal.com state, transcript — not just "does it sound right"), and `Why it matters if
it fails` (severity, so testing time gets prioritized correctly across a backlog of
pending checks).
