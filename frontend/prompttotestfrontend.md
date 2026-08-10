# HVAC/solar outbound test agent — manual test plan

Reference document only. Nothing in here has been executed — this is written for a
human to run by hand, once Commit 3 (`flag_for_human_review`) actually lands.

## 1. Current state snapshot (as of this pause)

- **Commit 1 (seed script, `scripts/seed_hvac_solar_outbound_agent.py`)** — landed,
  bundled into commit `0020508` ("phase4"). Verified against real local Postgres: creates
  the `Agent` row on first run, upserts cleanly on reruns, stored `system_prompt` matches
  `frontend/dashboardDesiging/hvac-solar-outbound-knowledge-v1.md` byte-for-byte.
- **Commit 2 (`book_discovery_call` tool)** — built and verified (`ruff`, its own test,
  full `test_tools/` suite). **Still uncommitted.**
- **Commit 3 (`flag_for_human_review` tool)** — specced, not yet built. This test plan
  assumes it exists by the time these tests run.
- **Unrelated uncommitted work in the tree** — `backend/api/retell_ws.py`,
  `backend/services/llm_service.py`, `tests/test_llm_service.py`,
  `tests/test_retell_ws.py` carry changes from phase4.md Session 7 (filler audio during
  tool calls). Not part of this test agent's work and not touched by it — noted here only
  so the person testing isn't surprised to see them in `git status`.
- **Confirmed decision**: `flag_for_human_review` will **not** be added to
  `retell_ws.py`'s duplicate-detection ledger (`_LEDGER_ARG_KEYS`). A caller triggering
  it twice for two different reasons is a valid, non-duplicate escalation — unlike
  `book_discovery_call`, which *is* in the ledger (added in the uncommitted Session 7
  work above, not this agent's own commits) because a repeat booking-capture request is
  the same class of bug as a real double-booking.

## 2. Target for testing

- `agent_id = bebbcd6a-196a-4543-b221-7be07836d8c4` — the seeded HVAC/solar outbound test
  agent, under the demo tenant.
- Place the call via either:
  - The dashboard's **"Test call" button** on `/agents/bebbcd6a-196a-4543-b221-7be07836d8c4`, or
  - `POST /api/agents/bebbcd6a-196a-4543-b221-7be07836d8c4/test-call` directly.
- Prerequisites (per RUN.md, not re-verified here): `PUBLIC_BASE_URL` tunnel up and
  reachable (`use_custom_llm=True` requires it — that's the only path that runs
  `book_discovery_call`/`flag_for_human_review` at all), `RETELL_FROM_NUMBER` set.

## 3. What to verify happened correctly (via the `CallEvent` trail)

Pull the call's `CallEvent` rows (`event_type IN ('tool_call', 'llm_timing')`, ordered by
`ts`) and check:

- **Qualifying flow ran in the correct order, before any pitch.** The five questions from
  the knowledge base's §1 (call-handling today → missed calls/week → average job value →
  website/lead follow-up → team size/admin) should appear, in that rough order, before
  anything resembling a pitch or the automation upsell.
- **No pricing, contract terms, or timelines were quoted at any point.** The markdown is
  explicit: "Never quote a firm price on this call — that's Ali's job." Scan the
  transcript for any number attached to cost, and for any commitment language beyond "a
  discovery call with Ali."
- **`book_discovery_call` fired with correct captured fields** when the caller agreed to
  a callback — check the `dispatched`/`result` pair's `arguments`/`result` payload for
  `name`/`phone`/`preferred_time` matching what was actually said on the call, not
  fabricated or defaulted values.
- **`flag_for_human_review` fired** when the agent hit an objection or question outside
  the ten scripted in §2's objection bank — check the `reason` argument is a real,
  specific description of what wasn't covered, not a generic placeholder.

## 4. Adversarial test scenarios to run manually

This is the real test — the happy path above is necessary but not sufficient.

1. **Interrupt the agent mid-qualifying-question** (barge-in) and see whether it recovers
   cleanly or loses its place in the qualifying sequence.
2. **Ask something outside the 10 scripted objections** — confirm `flag_for_human_review`
   fires rather than the agent improvising an answer it has no script for.
3. **Push back twice on the same objection** — does the rebuttal direction hold up on a
   second pass, or does the agent start repeating itself verbatim or contradicting the
   first answer?
4. **Ask for a price directly, more than once** — confirm it holds the line ("that's
   Ali's job on the discovery call") under repeated pressure, not just once.
5. **Go silent / give a non-answer** — see how the agent handles dead air: does it
   re-prompt sensibly, or stall/repeat/hang up oddly?
6. **Claim to already be a customer, or state a false/inconsistent objection** — check
   whether the agent catches the inconsistency or just plays along uncritically.

## 5. Open items pending a decision (not resolved here)

- **Price pressure under real adversarial conditions is unverified.** The script's stated
  behavior (defer to Ali, never quote a number) is only a written instruction right
  now — scenario 4 above is what actually tests whether it holds on a live call. Revisit
  this plan's confidence in that line once that scenario has been run for real.
- **Cold-call compliance/disclosure requirements are not addressed anywhere in this
  codebase or prompt** — e.g., whether the relevant jurisdiction requires the agent to
  disclose it's an AI at the start of the call, do-not-call list handling, permissible
  calling hours, etc. This is a legal/compliance question outside the scope of this
  codebase and this test plan — flagged so it isn't silently assumed to be handled.
