# Serial batch calling — one call at a time, event-chained

> **Status: written, unverified against anything real.** `uv run ruff check` clean,
> `uv run pytest` 701 passed, `uv run mypy backend` unchanged baseline (12 pre-existing
> errors before this work, 15 after — all three new ones are the same
> `sqlalchemy.sql.sqltypes.UUID[Any]` mapped-column quirk already tolerated elsewhere in
> this codebase, e.g. `prospect_service.py:632`, `lead_service.py:313/337/376`). **The
> migration (`1d467d365093_add_batch_runs`) has NOT been applied to the shared Neon
> database** — generated and reviewed, nothing more; applying it lands on teammates
> immediately (RUN.md / CLAUDE.md), so that's a deliberate hand-off, not an oversight.
> No real Retell call has gone through this path — the whole thing is mocked in tests at
> the `test_call_service.place_test_call` / `place_platform_agent_call` boundary, same as
> every other prospect-calling test in this repo. Frontend not started.

Source: design discussion 2026-09-02.

## The ask, and why the obvious answer was wrong

The operator wants small batches (5–10 prospects) dialed **one at a time, never two calls
live at once** — both to watch the run work and to avoid Retell concurrency/spend from
firing everything at once. The first framing was "a call every 5 minutes." That's the
wrong primitive: a 5-minute fixed timer either overlaps two calls (a real one runs long)
or wastes 4+ idle minutes after a 20-second no-answer/voicemail — and voicemail is most of
cold outreach. What's actually wanted is "start the next call the moment the previous one
*genuinely ends*" — an event, not a clock.

Retell already delivers that event: `call_ended` (and `call_analyzed` after it) land on
the existing webhook path and reach `call_service._fanout_post_call`, which already knows
how to hand a terminal call off to a downstream consumer (that's exactly what it does for
leads — ADR-011 — and for prospect outcome classification). Batch runs are a third
consumer hung off the same seam, not a new subsystem.

The 5-minute number survives only as a **stall-timeout fallback** (`batch_stall_minutes`,
config.py) — the ADR-007-style backstop for when a webhook never arrives, not the
mechanism that paces calls.

## Why not Retell's own Batch Call feature

Not used, and deliberately: `POST /prospects/batch-call` already doesn't touch it (every
dial goes through `create_outbound_call` → `POST /v2/create-phone-call`, one call at a
time, driven by our own loop) and this feature keeps that. Two reasons this matters, both
already documented at `call_service.py`'s `backfill_from_platform`: a Retell-dashboard
batch run creates no local `Call` row and fires webhooks at whatever tunnel URL happened
to be registered that day, so the outreach ledger would silently disagree with reality —
exactly the failure `sync-calls` exists to repair after the fact. Driving every dial
ourselves keeps `prospect_id` stamped on each call and `classify_call_outcome` firing
correctly, with no reconciliation gap to paper over.

## The concurrency problem this design is actually about

`_fanout_post_call`'s own docstring: **"Assume it runs more than once per call."**
`call_ended`, `call_analyzed`, and a later `reconcile_call` all reach a terminal
`Call.status` and all fan out. Naively advancing a cursor there double-dials the next
prospect. The fix is a conditional UPDATE used as a claim, not a lock:

```sql
UPDATE batch_run_items SET status='dialing' WHERE id=<next> AND status='queued'
```

Under Postgres READ COMMITTED, two concurrent callers targeting the same row serialize at
that row: the loser's UPDATE waits, then re-evaluates its own `WHERE status='queued'`
after the winner's commit and finds it already flipped, affecting zero rows. No
`SELECT ... FOR UPDATE` needed. The same shape guards the done-transition
(`mark_item_done_and_advance`, keyed on `call_id` + `status='dialing'`) and the stall
sweep (`mark_item_stalled_and_advance`).

**A real bug found by this design, not by inspection:** the first draft of the
"no row matched" branch called `await db.rollback()` before returning. Since a matched-zero
UPDATE writes nothing, there's nothing to undo — but `rollback()` unconditionally expires
every object in the shared session, and this function runs inside a caller's transaction
it doesn't own (a webhook handler, or a test's `db_session` fixture). That corrupted the
ambient transaction for anything running after it, surfacing as
`sqlalchemy.exc.MissingGreenlet` in three previously-passing tests the moment the fanout
hook was wired in. Fixed by simply returning — no rollback, no commit, when nothing was
written. `tests/test_batch_service.py::test_mark_item_done_and_advance_ignores_calls_outside_any_batch`
is the regression guard.

## What shipped

- **`backend/models/batch_run.py`** — `BatchRun` (agent, status, dynamic_variables,
  totals) and `BatchRunItem` (run_id, prospect_id, position, status, call_id,
  skip_reason). A real items table rather than a JSON id-list + cursor, specifically so
  `claim_next()` is one conditional UPDATE instead of a read-modify-write on a JSON blob.
- **Migration `1d467d365093_add_batch_runs`** — reviewed, not applied (see status above).
- **`backend/services/batch_service.py`** — `start_run` (reuses
  `prospect_service.batch_call_targets` unchanged for selection), `claim_next`,
  `advance_run` (loops past ineligible items — a skip produces no call, so nothing would
  ever re-trigger it if the loop stopped and waited), `_dial_item` (mirrors
  `/batch-call`'s per-prospect branch almost verbatim), `cancel_run`,
  `mark_item_done_and_advance` (called from the fanout hook), `mark_item_stalled_and_advance`
  (called from the stall sweep). `BATCH_RUN_MAX = 15`.
- **`call_service._fanout_post_call`** — one new branch under the existing
  `if call.prospect_id:` block: mark the batch item done, hand `run_id` to Celery.
  Deliberately does not dial inline — this runs on the webhook request path
  (<200ms budget, ADR-005) and dialing is an outbound HTTP call.
- **`backend/workers/batch_tasks.py`** — `advance_batch_run` (the actual dial, off the
  webhook path) and `sweep_stalled_batches` (reconciles via the platform, never advances
  on the clock's own authority — a genuinely long call must never get a second prospect
  dialed underneath it). Wired into the existing 300s Beat tick, same cadence as
  `sweep_stale_leads` / `sweep_stale_prospects`.
- **`backend/config.py`** — `batch_stall_minutes: int = 6`.
- **API** — `POST /api/prospects/batch-runs`, `GET .../batch-runs/{id}`,
  `POST .../batch-runs/{id}/cancel`. `POST /batch-call` (the original, fire-everything
  loop) is untouched and kept as-is; this is its paced sibling, not a replacement.
- **Tests** — `tests/test_batch_service.py` (service-level: single-dial-on-start,
  event-driven advance, double-fanout idempotency via a direct
  `handle_call_ended` → `handle_call_analyzed` sequence, skip-and-continue, cancel) and
  new cases in `tests/test_prospects.py` (router surface: create/get/cancel, tenant
  scoping, validation).

## Round 2 — picking who gets called, and per-prospect variables

Both from real use of the first cut (2026-09-02).

**1. `{{company_name}}` was being asked for once, for the whole batch.** The panel
rendered every placeholder a Retell agent declared as a required input. That's right for
the single-prospect drawer — the browser seeds each value from the one prospect being
called and the operator reads it before dialing — and wrong for a batch, where one typed
value would introduce the agent to twelve different companies under the same name.

The fix has to be server-side, and that's the interesting part: in a batch the browser
isn't in the loop for each dial. The operator starts a run and walks away; call #7 is
placed by a Celery worker twenty minutes later. So `backend/services/prospect_variables.py`
is the Python twin of `frontend/src/lib/dynamicVariables.ts` (same alias table — they
need keeping in sync, same as `_OPTIONAL_VARIABLE_NAMES` already does), and
`batch_service._variables_for` resolves per dial: run-level values first, that prospect's
own details layered on top. **Per-prospect values deliberately beat operator-typed ones**
— the inverse of the usual rule, and the entire point. Blanks are omitted rather than
sent as `""`, so a prospect with no city falls back to whatever was typed instead of
blanking it.

The panel now splits declared variables in two: per-prospect ones are listed as "filled
per prospect" with no input, and only genuinely batch-wide ones get a field —
`contact_name` among them, correctly marked optional (it was showing as required, which
was the other half of the complaint).

**2. Explicit prospect selection.** `prospect_ids` on `BatchRunRequest`: tick rows in the
list and exactly those get called, in that order. `batch_service._explicit_targets`
deliberately does *not* apply `batch_call_targets`' eligibility filters — those exist to
*choose* targets when nobody said who to call, and silently dropping a prospect the
operator can see ticked would be the surprising behaviour. The two exceptions are
non-negotiable rather than editorial: another tenant's ids (ADR-001) and prospects with
no phone number. Capped at `BATCH_RUN_MAX`, not the form's `limit` — `limit` means "how
many should I pick for you", which is meaningless once they've picked.

Frontend: a checkbox per row (disabled with a reason when the prospect has no phone),
selection held at page level (a row unmounts when research fills in its city and the tree
re-groups — same reason the call drawer lives there), a "select first N" shortcut, and
the panel listing every prospect it's about to call, in dial order, before you start it.

One test-suite trap worth recording: `_variables_for` reads the agent's declared
placeholders, so `tests/test_prospects.py`'s `placed_platform_calls` fixture — which
previously only faked the dial — was letting three router tests make a live call to
`api.retellai.com`. It now stubs the whole platform boundary.

## Deliberately left out (were artifacts of an earlier, bigger design)

- **Business hours checking.** Needed for a 4-hour, 50-call run; not for a 5–10 call run
  an operator starts and watches. Skipped — add if batches grow enough to walk out of the
  calling window on their own.
- **Per-item scheduled timestamps.** Same reasoning; not needed at this size.
- **Concurrency > 1.** Explicitly ruled out by the operator (Retell spend concern).
  `claim_next` only ever releases one item at a time by construction; raising it later
  would mean changing the claim query, not the whole design.

## Left for a follow-up session

- **Frontend.** A run-progress panel (start, live per-item status via polling
  `GET .../batch-runs/{id}`, cancel). Backend is fully drivable from `/docs` in the
  meantime.
- **Real-call verification.** Nothing here has dialed a real number yet. Needs: run a
  small batch against a real Retell agent, confirm the second dial actually waits for the
  first call's real webhook (not just the test's synthetic one), and deliberately let one
  call run stall (kill the tunnel mid-call) to watch `sweep_stalled_batches` recover it.
- **Migration apply.** Blocked on the user's go-ahead per CLAUDE.md's shared-Neon rule.

## Docs

CONTEXT.md / FRONTEND.md not yet synced — deferred until the frontend piece lands and the
feature is real-call verified, per the "sync after a batch of structural work, not
mid-flight" rule (`feedback-docs-sync-trigger` memory). This file is that structural
work's record until then.
