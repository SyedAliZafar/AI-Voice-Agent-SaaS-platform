# EFFICIENCY.md — how to work in this repo

This is about *how Claude (or anyone) should move through this codebase*, not about how
fast the app runs. For runtime performance budgets, see CONTEXT.md → "Performance
targets".

The premise: this repo is deliberately layered (model → schema → service → api, plus the
adapter pattern for voice platforms). That layering is correct — it's what makes adding a
third voice platform a new file instead of a rewrite — but it means a one-field change
legitimately touches 6–9 files. The waste isn't in the layering. It's in **rediscovering
the fan-out from scratch every time**. These rules exist to stop that.

## Before you edit

**Check CONTEXT.md's "Change recipes" table first.** It maps change types to the exact
files they touch, in order. If your change is in that table, you don't need to explore —
go straight to editing. Exploring anyway is the single most common waste in this repo.

**If it's not in the table, grep once, broadly.** Search the whole `backend/` tree for
the symbol in one pass rather than walking `models/`, then `schemas/`, then `services/`
as separate steps. One `Grep` across the tree tells you the real fan-out; four scoped
greps tell you the same thing four times slower.

**Read whole files, not fragments, when you're about to change them.** Partial reads
lead to edits that contradict a docstring or a guard clause 40 lines further down. The
docstrings in this repo carry real decisions (`api/deps.py`, `workers/prospect_tasks.py`,
`services/test_call_service.py` all encode "why it's like this" — ignoring them means
re-litigating a settled decision).

## While editing

**Follow the layer order: model → migration → schema → service → api → test.** Writing a
schema field before the model field exists, or a route before the service method, means
rework. The order isn't ceremony, it's dependency order.

**Batch independent edits into one message.** Separate files with no dependency between
them (e.g. the schema and the test) can be edited in parallel tool calls.

**Don't re-read a file to verify an edit landed.** `Edit`/`Write` error out if they fail.
A successful call is the confirmation.

**Don't run the whole suite after every file.** Make the full coherent change, then run
`uv run ruff check .` and `uv run pytest` once. (These are the required gates — see
CLAUDE.md.)

## Subagents

Spawn one only for genuinely open-ended fan-out — "where is X used across the whole
tree", "what's the current shape of the frontend", "does anything else depend on this
behavior". Those are searches whose answer you cannot predict.

Do **not** spawn one for a change already covered by a change recipe. The recipe *is* the
answer to the question the agent would go find, and the agent starts cold — it re-derives
context this session already has, which costs more than the edit itself.

## Keeping the map accurate

**When a change adds a new service, router, worker, model, or top-level frontend
component, update CONTEXT.md's structure tree in the same change.** Not later, not in a
follow-up.

This is the rule whose absence created the problem these docs were written to fix: the
tree drifted far enough that it omitted an entire subsystem (the prospecting pipeline,
ADR-006) and the in-flight Retell WebSocket work, and CLAUDE.md's tenant-scoping rule
pointed at a file that had been deleted. A stale map is worse than no map, because it's
trusted.

Same rule for decisions: if you make an architectural choice worth defending later,
it goes in CONTEXT.md as an ADR, or in a phase doc. If a phase doc supersedes an ADR,
update the ADR — don't leave two contradictory sources.

## Known open gaps (don't rediscover these)

These are documented in `phases/completed/phase0.md` / `phases/completed/phase3.md` and are *known*, not bugs to go find:

- `transfer_call`, `send_sms`, `lookup_customer` return fabricated success — not real yet.
- `CallEvent` has zero write sites — no per-tool-call/transfer/error record.
  (`Transcript.turns` itself is no longer a gap — see ADR-008/"Key data flows" in
  CONTEXT.md: `retell_ws.py` writes it live, `apply_retell_call_state` writes it post-call.)
- The Custom LLM websocket is non-streaming — one blocking LLM call per turn. phases/completed/phase0.md's
  latency spike says this will blow the 1.5s budget once tools are in play.
- Vapi's webhook has no signature verification (Retell's now does).
- No CI, no production deployment path.
- Clerk login is unbuilt; `CLERK_SECRET_KEY` is unread. Dev tokens come from
  `scripts/dev_token.py` (see RUN.md).
- `uv run mypy backend` reports ~11 pre-existing errors (openai types in `llm_service.py`,
  missing stubs for jose/celery, forward refs in `models/`). Not introduced by recent work
  — don't treat a clean mypy run as the bar until those are dealt with separately.
