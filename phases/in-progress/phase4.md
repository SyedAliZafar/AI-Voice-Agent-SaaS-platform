# Phase 4 — Voice Agent Remediation Plan

> **Status: in progress** — this file lives in `phases/in-progress/` deliberately.
> Sessions 1–7 are done, and 1–6 are real-call verified; **Session 7 still needs a
> real-call pass**, Session 8 is only partially scoped, and Sessions 9–11 haven't
> started. Move this file to `phases/completed/` with `git mv` only once *every*
> session is both done **and** real-call verified — passing tests is not the bar
> (see `promptstotest.md`, and every outliers.md finding that unit tests missed).

Source: Claude Code audit (2026-08-04) + ChatGPT cross-review. Two real
findings from the ChatGPT pass were folded into this queue (Session 2 and
Session 3) — everything else from that pass was repackaging, not new
information.

Run each session **separately**, in order. Do not bundle sessions. Paste
Claude Code's response back before starting the next one if anything
doesn't match what's expected below — don't proceed on trust.

Sessions 1–4 are cheap and low-risk. Session 5 is the highest-risk change
in the codebase — ask for a plan before touching code, and test on a
non-production agent first. Sessions 6+ assume Session 5 is done and stable.

---

## Session 1 — Stop the lying

**Why:** `transfer_call` and `send_sms` return hardcoded `{"success": True}`
without calling any real API. The agent tells callers a transfer or text
happened when it didn't. This is a trust/liability issue, not a backlog item.

```
In tools/transfer_call.py and tools/send_sms.py, the handlers return
hardcoded {"success": True} without calling any real API. This means
the agent tells callers a transfer/text happened when it didn't.
For now, make both handlers raise a clear NotImplementedError so this
fails loudly instead of silently lying to callers. Don't build the real
integration yet — just stop the fake success response.
```

---

## Session 2 — Wire the real credentials [DONE 2026-08-04]

Credentials now come from per-agent `ToolConfig.config` rows (`models/agent.py`),
loaded via `agent_service.get_tool_configs` and flattened into `caller_context` in
`retell_ws.py`. See ../../CONTEXT.md's ADR-003 note. Open gap: no CRUD route to actually
create `ToolConfig` rows yet — they have to be inserted directly.

**Why:** `book_appointment` and `create_lead` make real HTTP calls but
`calendar_api_key`/`crm_api_key` are never populated in `caller_context`.
These tools currently look wired but will fail against real credentials.

```
In caller_context construction (retell_ws.py, where tenant_id/agent_id/caller_number
are set), calendar_api_key and crm_api_key are never populated even though
book_appointment and create_lead expect them. Find where these should come from
(per-tenant integration settings, likely a Tenant or Agent config field) and wire
them into caller_context so these tools actually work instead of failing silently
against empty credentials.
```

---

## Session 3 — Catch LLM call failures

**Why:** Only `LLMConfigError` is caught around the LLM call in
`retell_ws.py`. A timeout, rate limit, or 5xx from the OpenAI/DeepSeek SDK
is unhandled and can crash the turn or the whole websocket mid-call.

```
In retell_ws.py's response_required branch, the call to llm_service.get_agent_response()
only catches LLMConfigError. A timeout, rate limit, or 5xx from the OpenAI-compatible
SDK is unhandled and will propagate up, likely crashing that turn or the whole websocket.
Add a broad except around the LLM call that falls back to a safe spoken message
("I'm having some trouble, let me get someone to help you" or similar) and doesn't
kill the connection.
```

---

## Session 4 — Instrumentation baseline

**Why:** No per-call latency or token/cost tracking exists. Needed before
touching the streaming architecture so you can actually measure whether
Session 5 helped.

```
Add timing instrumentation around both LLM calls in llm_service.py
(the initial call and the post-tool-call follow-up) using time.perf_counter().
Also capture response.usage (prompt_tokens, completion_tokens) from each
call. Persist both to a new CallEvent row per turn. I want a before/after
baseline before I touch the streaming architecture.
```

---

## Session 5 — Streaming + interruption handling (highest risk) [DONE 2026-08-04]

Shipped as `llm_service.stream_agent_response()` (a separate function from
`get_agent_response`, not a `stream=True` branch inside it — see ../../CONTEXT.md's ADR-009 for
why) plus a restructured `retell_ws.py`: each turn runs on its own cancellable task, a new
`response_id` cancels the stale one, and `settings.llm_streaming_enabled` (default on) is
the kill switch back to the old blocking behavior.

The plan surfaced a defect the original ask didn't cover: cancelling a turn mid-tool-call
(e.g. `book_appointment`'s Cal.com POST) could abandon a real side effect with no record of
it, or let the next turn re-attempt it since Retell's transcript carries no memory of the
first call. Fixed via `asyncio.shield()`'d tool execution, a dispatch-time
`CallEvent(event_type="tool_call")` trace, and a connection-scoped "already completed, do
NOT repeat" ledger injected into `conversation_history` each turn — see ADR-009 §4a-§4c.
Idempotency keys in `integration_service` remain the real fix and are still open.

**Why:** The whole handler blocks on one non-streaming LLM call, then sends
one frame. This is the root cause of latency, dead air, and the inability
to react to barge-in.

```
Our retell_ws.py custom-LLM handler is fully blocking: it awaits the
complete LLM response, then sends one single frame to Retell, so there's
no partial audio and no way to react to a caller barging in mid-response.
I want to move to streaming: set stream=True in llm_service.py's
completions.create() calls, yield chunks back through get_agent_response,
and send incremental {"content": chunk, "content_complete": False} frames
to Retell as they arrive. Also make the main receive loop non-blocking —
track the current response_id, and if a new response_required frame with
a different response_id comes in while we're still generating, cancel
the in-flight generation task instead of finishing it. Show me the plan
before you touch code, this is the highest-risk change in the codebase.
```

---

## Session 6 — Parallel tool execution [DONE 2026-08-07]

**Why:** `_execute_tool_calls` runs sequentially even when multiple tools
are requested in one turn — an easy win once streaming is in.

```
In llm_service.py's _execute_tool_calls, tool calls are run sequentially
in a for loop even when the LLM requests multiple tools in one turn.
Change this to run them concurrently with asyncio.gather instead.
```

Done: `_execute_tool_calls` now splits into two phases — a synchronous planning pass
(parse arguments, run `check_duplicate` for every call against the ledger snapshot as
it stands at the start of the turn, fire `dispatched`/`skipped_duplicate` events) with
no `await` anywhere in it, followed by `asyncio.gather` over whatever cleared the
duplicate check. This closes the gap Session 8's `check_duplicate` hook (ADR-009 §4c)
would otherwise have opened: naively parallelizing the old loop body would have let
two tool calls in the same turn race past the duplicate check against each other's
still-in-flight results. Because the planning pass never suspends, every
`check_duplicate` call in a batch sees the same start-of-turn snapshot regardless of
gather's scheduling, and `on_tool_event`'s `dispatched → result|error` ordering for a
given `tool_call_id` holds too, since both come from the same coroutine's own program
order. See `backend/services/llm_service.py:_execute_tool_calls`.

---

## Session 7 — Filler audio during tool calls [DONE 2026-08-07]

**Why:** Callers currently sit in dead silence during any tool call. Needs
the streaming slot from Session 5 to exist first.

```
Now that responses stream incrementally, add filler/backchannel audio
for tool calls that take longer than ~300ms. Use a small set of cached,
pre-recorded filler phrases ("let me check on that", "one moment") sent
as an early content frame before the tool result comes back, so callers
don't sit in silence during a Cal.com or HubSpot round-trip.
```

Done, with one deliberate deviation: **text, not audio.** ../../CONTEXT.md's "what not to
build" rules out custom TTS, and every frame retell_ws.py sends carries a `content`
*string* that Retell's own voice synthesizes — there is no pre-synthesized-audio field
in this codebase's Retell integration. So "cached, pre-recorded phrases" shipped as a
fixed tuple of pre-written phrases (`llm_service._FILLER_PHRASES`) picked in-process:
no LLM call, no synthesis on our side, so a filler still costs no latency of its own,
and it needs no protocol change — it rides the same content-frame path as every other
delta.

Implementation: `_run_tool_calls_shielded` was split so `_start_tool_calls_shielded`
returns the shielded future without awaiting it, letting `stream_agent_response` race
it against `TOOL_CALL_FILLER_DELAY_SECONDS` (0.3) via `asyncio.wait` and `yield` a
filler if the tool round hasn't finished. The shield still wraps the future that's
awaited during the wait, so a barge-in mid-filler stops the speech without abandoning
the in-flight tool call (ADR-009) — covered by a test. Fires once per slow tool round,
so a turn with two sequential slow rounds gets one filler each. No changes to
retell_ws.py.

---

## Session 8 — Server-enforced confirmation gating [PARTIAL 2026-08-05]

One slice of this shipped as a direct fix for a real bug (outliers.md §1: a real
double-booking on a live test call), not the full session as originally scoped. Done:
`llm_service._execute_tool_calls` now takes a `check_duplicate` callback, consulted in
code before every side-effecting dispatch; `retell_ws.py` wires it to the existing
`completed_tool_calls` ledger (ADR-009 §4c) via `_find_duplicate_ledger_entry` — a
request matching something already completed this call never reaches the real handler,
regardless of whether the model complies with the system-prompt note. Not done: the
`requires_confirmation` ToolConfig field and checking the caller's most recent turn for
an affirmative confirmation *before* a first-time dispatch, which is what this session
was originally about — this only stops *repeats* of something already done, it doesn't
gate the first attempt. See ../../CONTEXT.md ADR-009 §4c for the implementation.

**Why:** Consequential tool calls (bookings, CRM writes) fire the instant
the LLM decides to, with no code-level check that the caller confirmed.
Currently 100% prompt-dependent.

```
Add a requires_confirmation boolean field to ToolConfig for side-effecting
tools (book_appointment, create_lead, and eventually send_sms once it's
real). Before _execute_tool_calls runs a tool flagged this way, check that
the caller's most recent turn actually contains an affirmative confirmation
— don't rely on the system prompt alone to gate this. If there's no
confirmation, ask for one instead of executing.
```

---

## Session 9 — Real escalation logic + real transfer

**Why:** Escalation is currently 100% LLM judgment with no counter, and
`transfer_call` (fixed to fail loudly in Session 1) still needs a real
implementation.

```
Add a failed_intent_count or similar counter to call state, incremented
on tool errors or low-confidence/repeated-clarification turns. When it
crosses a threshold (start with 2), trigger transfer_call deterministically
in code rather than leaving it entirely to LLM judgment. Also wire
transfer_call's handler to actually call Retell's or Vapi's real
transfer/forward API instead of the stub from Session 1.
```

---

## Session 10 — Fix personalization gap on the custom-LLM path

**Why:** `_provision_custom_llm_agent()` rejects `system_prompt_override`
outright, so the per-prospect research brief only reaches Retell's hosted
LLM — never the actual DeepSeek/OpenAI path this project is meant to run on.

```
test_call_service._provision_custom_llm_agent() currently rejects
system_prompt_override outright, so the per-prospect research brief
built by script_service.build_prospect_prompt() only gets injected on
the hosted-LLM (Retell's own brain) path — never on the DeepSeek/OpenAI
custom-LLM path, which is the architecture we're actually building toward.
Fix this so personalized prompts work on the custom-LLM path too.
```

---

## Session 11 — Real send_sms and lookup_customer

**Why:** Last two stubs. Same pattern as the tools fixed in Session 2.

```
Wire tools/send_sms.py to actually call Twilio, and tools/lookup_customer.py
to actually query the CRM. Both currently return hardcoded stub responses.
Follow the same pattern as book_appointment/create_lead — real API call,
proper error surfaced back to the LLM on failure, no fabricated success.
```

---

## Notes

- Sessions 1–4: can realistically be done in one day.
- Session 5: review the plan before letting Claude Code write anything;
  test against a non-production agent.
- Skipping Session 4 means no way to prove Session 5 actually helped or
  to catch a regression.
- If any session's diagnosis contradicts what's documented here (e.g.
  claims something is already handled that's flagged missing above),
  paste the response back before moving to the next session.
