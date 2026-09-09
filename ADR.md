# ADR.md — Architecture decisions

> Split out of [CONTEXT.md](CONTEXT.md) so the standard per-change read stays small.
> CONTEXT.md carries a one-line index of these; read the full entry here only when your
> change touches that decision. Where a phase doc contradicts an ADR, the phase doc wins
> — see the note at the top of CONTEXT.md.


### ADR-001: Multi-tenancy via row-level isolation
Every model has a `tenant_id` FK (`TenantMixin`, `backend/models/base.py`). No
schema-per-tenant — too much operational overhead at this stage. Revisit if we hit
500+ tenants with data isolation requirements.

Tenant resolution is a **FastAPI dependency, not middleware**: `get_current_tenant`
(`backend/api/deps.py`) decodes the bearer JWT's `tenant_id` claim and every `/api/*`
route takes it via `Depends(...)`, never from a client-supplied query param. An earlier
`backend/middleware/tenant.py` did this via `BaseHTTPMiddleware` — it was written, never
registered, and has since been deleted, because middleware can't raise per-route 401s,
can't participate in dependency injection (so tests can't override it), and is skipped
for WebSocket scopes, which matters for the Retell custom-LLM socket. See `phases/completed/phase0.md`
Task 2 for the full audit that drove this.

`/webhooks/*` are the deliberate exception: Retell/Vapi can't send our JWT, so those
routes stay unauthenticated by this mechanism. They still lack platform signature
verification — a known open gap, see `backend/api/webhooks.py` and `phases/completed/phase0.md`.

### ADR-002: Voice platform adapter pattern
`voice_platform.py` defines an abstract `VoicePlatformAdapter` with methods like
`create_agent()`, `assign_phone_number()`, `handle_webhook()`. Retell and Vapi each
get their own adapter. This means adding a third platform (Bland AI, PlayHT) is a
new file, not a rewrite.

### ADR-003: LLM tool execution is server-side
The LLM (DeepSeek) receives the caller's transcribed text and decides which tool to call.
Tool execution happens in our backend, NOT in the voice platform. This gives us:
- Full control over what data the LLM can access
- Audit logging of every tool invocation
- Ability to add guardrails before and after tool execution
- No vendor lock-in on the tool layer

Per-tool integration credentials (`calendar_id`/`calendar_api_key` for
`book_appointment`, `crm_api_key` for `create_lead`) live in `ToolConfig.config`
(one row per `agent_id` + `tool_type`, see `models/agent.py`). `retell_ws.py` loads
every `ToolConfig` row for the call's agent via `agent_service.get_tool_configs` and
flattens each `config` dict into `caller_context` before the LLM call, so tool
handlers read them via `caller_context.get(...)`. There's no CRUD route for
`tool_configs` yet — rows have to be inserted directly (seed script or DB) until one
exists.

Because that flattening ignores `tool_type` — every row's `config` lands in one shared
`caller_context` — a tool can read credentials a *different* tool's row supplied.
`check_availability` does exactly this on purpose: it reads the same
`calendar_id`/`calendar_api_key`/`calendar_timezone` the `book_appointment` row already
provides, so adding it needed no new `ToolConfig` row and no seed-script change. Worth
knowing before assuming a row is scoped to the tool it's named after.

### ADR-004: WebSocket for live call monitoring
The dashboard's live call view uses WebSocket (not SSE) because we need bidirectional:
the operator can barge-in, whisper, or force-transfer. Redis PubSub distributes call
events from the webhook handler to all connected WebSocket clients watching that call.

### ADR-005: Celery for post-call processing
Transcript analysis, sentiment scoring, metric rollups, and CRM sync all happen async
after the call ends. The webhook handler enqueues tasks and returns 200 immediately.
This keeps webhook response time under 200ms (voice platforms timeout at 5-10s).

**Retell's webhook contract** (learned the hard way — see phases/completed/phase3.md): exactly three
events, `call_started` / `call_ended` / `call_analyzed`, and the call object is **nested**:
`{"event": "call_ended", "call": {"call_id": ..., "duration_ms": ..., "transcript": ...}}`.
There is no `transcript_update` webhook — that's a *websocket* message type from the
custom-LLM protocol, not a webhook. Sentiment arrives on `call_analyzed`, not `call_ended`.

Retell must also be *told* where to send these: `webhook_url` is set per-agent at
provisioning time (`retell_adapter.create_agent_with_llm` /
`create_agent_with_custom_llm`) from `PUBLIC_BASE_URL`. A Retell agent's webhook URL is
fixed at creation, so `test_call_service` re-provisions when it changes — otherwise an
agent created before a tunnel existed keeps pointing at nothing forever.

`Transcript.turns` now has two writers, not one: `backend/api/retell_ws.py` writes it
turn-by-turn as a live custom-LLM call happens (`call_service.record_turns`, called after
each response is sent — off the turn-latency path), and `apply_retell_call_state` parses
Retell's post-call `transcript_object` as the authoritative final write, which also covers
the hosted-LLM path (no WS handler to have written anything live). Retell always sends the
*full* transcript so far, live or post-call, never a delta — so both writers are idempotent
wholesale replaces, safe to call repeatedly.

### ADR-007: Webhooks are the fast path, reconciliation is the source of truth
Webhook delivery is best-effort: the dev tunnel may be down, `PUBLIC_BASE_URL` may be
unset, the tunnel host changes on every restart. A missed `call_ended` used to strand a
call at `in_progress` permanently, with 0s duration and no transcript.

So the platform is treated as authoritative and pollable, not just push-based:
`call_service.reconcile_call()` fetches `GET /v2/get-call/{id}` and applies the real
state; `POST /api/calls/sync` runs it across every still-`in_progress` call for the
tenant. Both the webhook path and the reconcile path write through **one** function,
`apply_retell_call_state()` — if they were separate writers they could disagree about
the same call's outcome.

A third path, `call_service.backfill_from_platform()` (`POST /api/prospects/sync-calls`),
pulls the platform's *entire* call history (`retell_adapter.list_call_history`, paginated
`/v2/list-calls`) and upserts a `Call` row per entry keyed on `external_id`. It's the
only path that can see a call this backend never placed — a batch run started from
Retell's dashboard (ADR-012) creates no local row and fires webhooks at whatever tunnel
URL was registered that day. Each call is matched to a prospect by
`prospect_service.phone_match_key` (last 10 digits, so E.164 `+442077335265` and national
`020 7733 5265` collide), still written through `apply_retell_call_state`, and afterward
`resync_prospects_from_calls` recomputes each touched prospect's `call_count` /
`last_called_at` / `status` from its full set of `Call` rows. Idempotent — re-run freely.

**Hanging up a live call** (`call_service.end_call`, `POST /api/calls/{id}/end`,
`scripts/kill_calls.py`) follows the same rule: it tells Retell to stop the call, then
*reconciles* rather than writing a terminal status itself, so `apply_retell_call_state`
stays the single writer and this path can't disagree with the webhook about how the call
ended. The hangup goes first and is allowed to raise; the reconcile is best-effort
tidying. If it fails, the row stays `in_progress` for the webhook or `/sync` to settle —
the call is still down, which is the part that mattered.

The CLI exists *alongside* the endpoint on purpose: the moment you most need to stop a
call is often the moment the API server, worker, and tunnel are all down. `kill_calls.py`
needs only `RETELL_API_KEY` — no database, no tunnel, no app import. It lists by default;
`--all` and `--call-id` are the destructive forms. "Live" is asked of Retell
(`adapter.list_live_calls`, filtering `call_status=ongoing`) rather than read from our
`calls` table, which can't be trusted for it — an in_progress row may be a call that
ended hours ago with a lost webhook.

Status mapping lives there too: `disconnection_reason` distinguishes `resolved` from
`escalated` (`call_transfer`) and `failed` (dial failures, `error*`), which is richer than
the "everything that ended is resolved" assumption this code started with. The raw reason
is also kept verbatim on `Call.disconnection_reason` (alongside the coarse `status`) plus
a computed `Call.answered_by_human` — `status` alone collapses voicemail / declined /
rang-out into `failed`, and prospect outcome classification (ADR-006) needs them apart.

Signature verification (`X-Retell-Signature`, HMAC-SHA256 over the raw body with a
5-minute replay window) is delegated to the official `retell-sdk` — see
`RetellAdapter.verify_webhook_signature`. It must run against the **raw** request bytes,
which is why `webhooks.py` reads the body itself rather than taking a parsed Pydantic
model as a route parameter.

**2026-08-10 update — the stale-URL half is now self-correcting.** The preflight above
stops a wasted call but still leaves the operator doing the same manual recovery every
time: read the new hostname out of `docker compose logs`, paste into `.env`, recreate the
API container (because `docker compose restart` doesn't re-read `.env`). That ritual cost
four billed test calls (2026-08-04, -08-05, -08-08, -08-10) — always the same root cause,
a cloudflared *quick* tunnel minting a fresh `https://<random>.trycloudflare.com` on every
start.

`PUBLIC_BASE_URL` now accepts the sentinel **`auto`** (`backend/services/public_url.py`),
which resolves the current hostname from cloudflared's own metrics server
(`GET /quicktunnel` → `{"hostname": ...}`, verified empirically against
`cloudflare/cloudflared:latest` before being coded against). A literal URL always wins, so
the named tunnel, production, and every existing test that sets a concrete URL are
untouched — that "explicit wins" property is deliberate and is what let this land without
changing a single existing test. Callers pass their own configured value in
(`get_public_base_url(settings.public_base_url)`) rather than the module reading settings
itself, so `test_call_service`'s settings stay independently patchable.

Two supporting changes: `tunnel-quick` gained `--metrics 0.0.0.0:20241` (mirroring the
named `tunnel`, which already had it) plus `restart: unless-stopped` — its absence is why
the 2026-08-08 container sat `Exited (255)` for 19 hours with nothing bringing it back.
And because a stale cached URL can outlive a restart inside a long-lived API process, the
custom-LLM preflight re-resolves once with `force_refresh=True` and retries before
failing, so a tunnel restart is a non-event rather than a failed call.

This is a workaround for the quick tunnel's design, not a replacement for the named one —
Option A in RUN.md remains the recommendation, and makes all of the above moot.

Reconciliation repairs a dead tunnel after the fact; it doesn't stop one from wasting a
call in the first place. The custom-LLM path (below) additionally *preflights*
`PUBLIC_BASE_URL` reachability before dialing (`backend/services/tunnel_check.py`,
called from `test_call_service._provision_custom_llm_agent`) — a dead tunnel fails the
test-call request immediately with a 422 instead of Retell dialing a websocket nobody's
listening on. Same root cause the fix above targets (a quick tunnel can die mid-session
while `docker compose ps` still reports `Up`), different point in time: this catches it
*before* the call, reconciliation catches it *after*. Hosted-LLM agents are exempt —
that path is designed to work with no tunnel at all.

### ADR-008: Provider-agnostic LLM, chosen per agent
`llm_service.py` was hardcoded to one module-level `AsyncOpenAI(base_url="https://api.deepseek.com")`
— trying GPT meant editing that file. DeepSeek and OpenAI both speak the OpenAI-compatible
chat-completions protocol, so "which provider" reduces to `api_key` + `base_url` + `model`:

- A model id resolves to a provider via `MODEL_CATALOG` (the UI's dropdown source) or,
  for an id not yet listed, a prefix guess (`gpt-*`/`o1*`/`o3*` -> openai, `deepseek-*` ->
  deepseek) — `llm_service.provider_for()`. Unresolvable, or resolvable but missing its
  API key, both raise `LLMConfigError` rather than a raw SDK error.
- Exactly one `AsyncOpenAI` client per provider, cached (`get_client`, `@lru_cache`) — not
  per call. phases/completed/phase0.md measured ~2.5s of dead air on a cold client (DNS + TLS); constructing
  one per turn in the WS handler would reintroduce that on every response.
- **Caching alone never covered the *first* call, though** — the cache has to be populated
  by someone, and whoever does it pays the handshake. On 2026-08-14 that someone was a
  real caller: the one agent configured for `gpt-4o-mini` (19 of 20 use the DeepSeek
  default) opened the process's first-ever OpenAI connection, spent **2.6s** reaching its
  first token, and the callee said "Hello?" into the silence — which Retell read as a
  barge-in, cancelling and restarting the half-spoken greeting (ADR-009). Re-measured
  head-to-head: cold 2.76s (openai) / 0.98s (deepseek), warm 0.5–1.1s both; idle gaps
  between turns cost nothing, so it is strictly a first-request cost, not connection
  churn. `llm_service.warm_up_providers()` now opens each *configured* provider's
  connection from `main.py`'s lifespan, which drops that first call to 0.63s / 0.62s. It
  uses `models.list()` (no tokens) rather than a throwaway completion, runs as a
  background task so it can never delay or — offline — block startup, and swallows its
  own failures: the worst case of a failed warm-up is the latency we already had.
- `Agent.llm_model` (empty string = "use `settings.default_llm_model`") makes the choice
  per-agent, not global — set via the "Conversation engine" card's model `<select>`
  (`GET /api/agents/models` reports the catalog plus which providers are `configured`).
  Only takes effect on the `use_custom_llm` path; Retell's hosted LLM ignores it.
- `get_agent_response(..., tools_enabled=...)` — `False` omits the `tools` kwarg entirely
  (not `tools=None`; the SDK's `tools` param isn't `Optional`, so `None` would literally
  serialize as `"tools": null`). This is what lets the sandbox (below) run a text chat
  without risking a real `book_appointment`/`create_lead` call.

### ADR-009: Streaming custom-LLM responses with barge-in cancellation

phases/in-progress/phase4.md Session 5. `backend/api/retell_ws.py`'s Custom LLM websocket handler used to
be fully blocking: one `llm_service.get_agent_response()` call per turn, then a single
`content_complete: True` frame — dead air until the whole reply (plus any tool
round-trips) was ready, and no way to react to a caller talking over the agent, since the
receive loop couldn't even process Retell's `ping_pong` while the LLM call was in flight.

**Streaming.** `llm_service.stream_agent_response()` is a new async generator, not a
`stream=True` branch inside `get_agent_response` — that function has three other callers
(`sandbox_service.chat`, `scripts/check_custom_llm.py`, and retell_ws's own kill-switch-off
path below) that must keep its exact blocking behavior, and duplicating the tool-call loop
was a smaller risk than threading a stream flag through code with correctness properties
(the tool-call loop, the fallback text, `llm_events` instrumentation) other callers depend
on. `retell_ws._generate` sends one `{"content": chunk, "content_complete": False}` frame
per delta, then exactly one terminal frame (empty on success — content already streamed;
a fallback message if something failed, so an error before any delta produces the same
single-frame wire shape the old blocking path did).

**Kill switch.** `settings.llm_streaming_enabled` (default `true`) — `false` makes
`_generate` call the untouched `get_agent_response` instead, restoring the pre-streaming
behavior byte-for-byte. Given this is the highest-risk change in the codebase, the escape
hatch is a config flag + container recreate, not a git revert.

**Barge-in cancellation.** Each `response_required`/`reminder_required` turn runs on its
own `asyncio.Task`. If a new one arrives with a *different* `response_id` while a turn is
still generating, the receive loop cancels and awaits the stale task before starting the
new one — deliberately only on a response_id change, not on `update_only` interim speech,
which fires on noise/backchannel ("mhm") too often to safely mean "the caller is talking."
The receive loop no longer blocks on generation, so `ping_pong` keeps being answered while
a turn streams.

**ADR-009a: not every barge-in is an interruption.** Cancelling on *every* response_id
change turned out to be too eager, and call `b23851eb` (2026-08-19) is the case that
proved it: Retell reports an interruption for any caller audio at all, so a grunt shredded
each reply after two or three words, the fragments made the prospect say "what?", and that
"what?" cancelled the next reply too. Every agent turn for 100 seconds was 2–6 words long;
the prospect's own summary was *"the problem is you stopped too many times."* The model
then inferred from its own mangled context that it had a bad line, apologised for a
non-existent fault, and reached for `transfer_call` — which raises (see below).

`retell_ws._should_let_turn_finish` gates the cancellation on two independent tests, either
sufficient to *absorb* the barge-in: the turn is younger than
`settings.barge_in_min_turn_ms` (700ms — audio overlapping the very start of a reply is
far more likely to be the tail of the caller's own sentence than a reaction to words they
have not heard yet), or the caller's newest utterance is pure backchannel
(`_FILLER_UTTERANCES` — "yeah", "mhm", "what?"; deliberately excludes anything carrying a
request, so "stop", "wait", "no thanks" always cut the agent off instantly).

Absorbing is *not* dropping the frame: the new `response_id` is still answered, just after
the current turn finishes, so every turn Retell asks for gets exactly one terminal frame
and no reply is ever left truncated. Because Retell built the queued frame's transcript
before the absorbed turn finished, `_with_agent_turn` splices the just-spoken reply back
in — without it the next generation cannot see what it just said and repeats it.
`settings.barge_in_ignore_filler=false` plus `barge_in_min_turn_ms=0` restores the old
always-cancel behavior.

**Reply length.** Two mechanisms, deliberately separate. `retell_ws._SPEECH_BLOCK` asks for
one to three sentences (~40 words) so replies *end* naturally; `llm_service.MAX_TOKENS`
(200, was 1024) is only a hard stop bounding the pathological case, since a cap alone
truncates mid-word — which sounds exactly like the bug above. Short replies also spend
less time exposed to being interrupted at all.

**`transfer_call` is not registered.** Its handler raises (no real voice-platform transfer
is wired up yet — phase4.md), and offering an unimplemented escape hatch to the model is
worse than offering none: under stress it reaches for it, gets an error it cannot act on,
and has no fallback. `flag_for_human_review` is the working escalation path until the
transfer integration lands.

**Barge-in must interrupt speech, never a side effect.** This is the part worth
remembering: `asyncio.CancelledError` lands wherever a cancelled task is currently
suspended, and if that happens to be `await client.post("https://api.cal.com/v1/bookings")`
inside `book_appointment`'s handler, the request may already be on the wire — cancelling
the task doesn't un-book it, it just makes us lose track of whether it happened, and
because the result never re-enters the message history, Retell's transcript for the next
turn has no idea a booking fired, so the model can re-attempt it. So tool execution is run
on its own task and the outer await is `asyncio.shield()`ed
(`llm_service._run_tool_calls_shielded`) — a barge-in stops the audio immediately but lets
an in-flight tool call finish. That shielded task, and the fire-and-forget
`CallEvent(event_type="tool_call")` write for each tool-call phase
(`call_service.record_tool_event`, via `_execute_tool_calls`'s `on_tool_event` sink), are
tracked in one per-connection set and drained (with a bounded wait, re-checked rather than
a single `gather`, since the "result" write task is only created after the drain begins)
in `llm_websocket`'s `finally` on disconnect. The same shielding now also covers
`_persist_and_publish_turn` once a turn's terminal frame has gone out — a turn that's
already fully spoken must survive a same-instant barge-in or disconnect too.

Even with all of that, a barge-in mid-tool-call still leaves the *next* turn with no
built-in reason not to re-attempt the same action, since Retell owns the transcript and it
carries no record the first call happened. `retell_ws.py` keeps a connection-scoped ledger
of completed side-effecting tool calls (`book_appointment`, `create_lead`, `send_sms`;
deliberately not `lookup_customer` or `check_availability` — repeating a read is harmless,
and for availability it's actively *correct*, since a slot can be taken by someone else
mid-call) and injects a bounded "already completed, do NOT repeat" note ahead
of `conversation_history` on every turn.

**§4c update, 2026-08-05 — that note alone isn't enough, so it's now enforced in code
too.** A real test call hit exactly the gap this paragraph originally left open: the model
re-dispatched `book_appointment` for a slot it had *just* booked, in a completely ordinary
sequential turn — no barge-in, no cancellation involved. It happened because the caller
talked over the agent's own confirmation and the follow-up ("four PM?") read as ambiguous;
the ledger note, being pure prohibition with no alternative action, lost to what looked
like a live request. Cal.com's own conflict check caught that specific repeat, but the
model then booked a *different* slot instead — two real bookings for one appointment. Full
writeup: `phases/in-progress/outliers.md` §1.

Fix: `llm_service._execute_tool_calls` takes an optional `check_duplicate(tool,
arguments) -> synthetic_result | None` callback, consulted *before* every side-effecting
dispatch — a match means the real handler never runs at all. `retell_ws.py` wires this to
`_find_duplicate_ledger_entry`, matching against `completed_tool_calls` with the exact same
identifying-argument normalization `_ledger_entry` used to store it (`_ledger_args_key`,
shared by both so the two sides of the comparison can't drift). On a match, the LLM gets a
synthetic tool result (`_duplicate_tool_result`) instead of dispatching — and that result
carries an explicit instruction ("tell the caller it's already done"), not just a
negative, because the same real call showed a bare prohibition isn't salient enough at the
moment the model actually needs to act on it. This is the code-level backstop the prompt
note was missing: it doesn't depend on the model choosing to comply. It's also the first
slice of phases/in-progress/phase4.md Session 8 (server-enforced confirmation gating) — the
`requires_confirmation`-before-first-attempt half of that session is still open.

This still isn't a substitute for real idempotency keys in `integration_service` — the
duplicate check only catches a *repeat* dispatch our own process observed; it can't help
if the process restarts between attempts. That remains open.

**§4c update, 2026-08-06 — the ledger needed a capability, not just a check, for
cancel/reschedule.** A different real call hit a gap the above fix doesn't cover: the
caller asked to reschedule a booking, the agent said "let me cancel the nine AM," but no
cancel/reschedule tool existed at all — the model fabricated an *action taken*, not just
a fact, leaving a silent real double-booking. Full writeup: `phases/in-progress/outliers.md` §5.

Fix: two new tools, `cancel_appointment`/`reschedule_appointment`
(`backend/tools/cancel_appointment.py`, `reschedule_appointment.py`), backed by new
`integration_service.cancel_calendar_booking`/`reschedule_calendar_booking` functions —
`POST /v2/bookings/{bookingUid}/cancel` and `.../reschedule`, same `CAL_API_VERSION` as
booking creation. Deliberately two tools mirroring Cal.com's own two atomic endpoints,
not a merged tool composing "cancel then book_appointment again," which would reintroduce
a real race (cancel succeeds, rebooking fails, caller loses the appointment entirely).
Verified against the real API before coding — a live cancel and a throwaway
book→reschedule→cancel probe, not docs alone — and that probe surfaced a real,
easy-to-miss contract detail: **a successful reschedule returns a NEW `uid`, not the one
sent in** (Cal.com supersedes the original booking rather than mutating it; the new
booking carries `rescheduledFromUid` back to the old one).

That in turn exposed a pre-existing gap: `book_appointment.py`'s handler returned only
the numeric Cal.com `id`, discarding `uid` — but cancel/reschedule need exactly the
string `uid`. Now captured and returned as `booking_uid`. The ledger gained
`_LEDGER_EXTRA_RESULT_KEYS`, a second per-entry field alongside the existing
`result_id`, so the model can read a booking's `uid` straight out of the ledger note it
already sees every turn — no new backend-side lookup, same principle as the rest of
§4c: the model supplies identifying arguments, the backend only matches/enforces. The
uid-rotation risk self-resolves without special-casing: a reschedule is its own ledger
entry keyed on the *old* uid it acted on, carrying the *new* uid in `extras`, so a
genuine follow-up change reads the current uid rather than being blocked as a duplicate
of the now-stale original request. Both new tools are tracked by the same
`check_duplicate` mechanism above, keyed on `booking_uid`.

**§4c update, 2026-08-06 (later same day) — a timeout is not a confirmed failure, and
the prompt instruction alone didn't hold.** Real-call verification of the fix above
found a `reschedule_appointment` request time out client-side; the bare error result
this produced was indistinguishable from a confirmed rejection, and the model told the
caller it succeeded anyway. It happened to be true — Cal.com had processed the request
before the client gave up waiting — but only by luck; the same timeout on a genuinely
failed request would have produced an identical false confirmation, despite the system
prompt already saying not to claim success without tool confirmation. Full writeup:
`phases/in-progress/outliers.md` §6.

Fixed in code: `integration_service.IntegrationTimeoutError`, raised when
`httpx.TimeoutException` interrupts the POST in `book_calendar_slot`/
`cancel_calendar_booking`/`reschedule_calendar_booking` — applied to all three, since
nothing about the ambiguity is specific to reschedule. `backend/tools/base.uncertain_result`
gives each tool's handler a result shaped `{"status": "uncertain", ...}`, deliberately
not `{"error": ...}`, so the distinction survives in the `CallEvent` audit trail at a
glance, not only in prose the model has to parse correctly mid-call. `retell_ws._ledger_entry`
excludes it from the ledger — an unconfirmed outcome isn't "already done."

**Instrumentation.** `llm_events` keeps the same `{stage, model, duration_ms,
prompt_tokens, completion_tokens}` shape the Session 4 baseline established — no schema
change to `CallEvent(event_type="llm_timing")` — plus two additive keys: `ttfb_ms` (time to
the first content delta, the metric streaming exists to move) and `streamed: True` (so
before/after rows are distinguishable in the same table).

### ADR-010: The agent speaks first, via a begin message on `call_details`

Found on a real test call: the agent stayed silent after connecting and only spoke once
the person who'd been dialed said something first. Backwards for outbound cold calls —
the agent placed the call, so it owes the opener, and every prompt in
`scripts/agent_templates/` is written around delivering one.

Cause: Retell only sends `response_required` *after* the other party speaks, and
`retell_ws.py`'s receive loop explicitly did nothing with the one-time `call_details`
frame that arrives at connect. Nothing was broken in the prompts; there was simply no
code path that could produce a first utterance.

Fix: `call_details` now starts a normal generation turn with `response_id: 0` (what
Retell's protocol reserves for the begin message), through the same `_generate` used by
every other turn — so streaming, barge-in cancellation, fallback text, transcript
persistence and `llm_events` all apply to the opener too, with no parallel code path.

**The opener waits, and it arrives in three beats.** Both came out of listening to real
calls. The agent spoke the instant the call connected, talking over the "Hello?" of
whoever picked up.

The pause is `settings.greeting_delay_ms` (default 1500), sent to Retell as
`begin_message_delay_ms` when the agent is provisioned — **not** a sleep in
`retell_ws.py`. That was the first attempt and it was the wrong layer: Retell opens the
LLM websocket during call *setup*, so a timer started on `call_details` runs out while
the phone is still ringing. It passed its unit test, held the audio exactly as designed,
and changed nothing on a real call, because it was measuring from an event that isn't
pickup. Retell is the only side that knows when the call was answered. The value is part
of the `voice_config["retell_custom"]` cache key alongside `ws_url`/`webhook_url`, since
it's fixed on the Retell agent at creation — without that, changing it would silently
never reach an already-provisioned agent.

If they speak while the opener is still generating, the receive loop cancels it and their
turn is answered normally — `current_response_id` is a sentinel object for that window
precisely so an incoming `response_id: 0` reads as a barge-in rather than as Retell
resending the same turn.

The opener also used to deliver identity, hook, findings and the ask in one breath, which
is what a recorded pitch sounds like. It's now three turns with a real reply between each
(`shared.CALL_OPENING_SEQUENCE`, applied to every leaf): who's calling → what this is
about → the ask. Because each turn is stateless, the block tells the model to determine
its beat by *counting its own prior turns in the transcript* rather than inferring from
feel — without that it collapsed beats 2 and 3 together and then re-asked the interest
check. `compose.py`'s qualifying-flow heading had to change with it: it previously read
"ask early ... for Long Detail", which directly contradicted the beats and made Long
Detail jump into qualifying at Beat 2.

Two more things are deliberate:
- **The opener is LLM-generated from the agent's own prompt, not static config text.**
  Each service line has its own hook (`agent_templates/services.py` — AI Automation's
  "you're talking to the proof" can't be reused by SEO/Web Dev), so a hardcoded
  `begin_message` on the Retell agent would either be generic or need duplicating per
  leaf. `_BEGIN_MESSAGE_INSTRUCTION` is a synthetic system turn — present only in that
  one LLM call, never persisted — telling the model to deliver its opener rather than
  answer a caller turn that doesn't exist.
- **Tools are disabled for this turn** (`tools_enabled=not greeting`): nothing can
  legitimately need a booking or a lookup before the other party has said a word.

`_call_already_in_progress` guards the reconnect case: the config frame sets
`auto_reconnect: True`, so Retell can replay `call_details` mid-call, and re-greeting
there would talk over a conversation in progress and restart the pitch. A call object
carrying a transcript is a reconnect, not a fresh start.

### ADR-006: Prospecting pipeline (Prospector + Researcher agents)
Before a call can happen, something has to decide *who* to call. The prospecting
pipeline sources and ranks call targets, upstream of everything else in this doc:

1. **Agent 1 — Prospector** (`places_service.py` + `workers/prospect_tasks.py`'s
   `discover_prospects`): searches Google Places for businesses matching a query/location,
   upserts them as `Prospect` rows (`models/prospect.py`) via
   `prospect_service.upsert_from_places()`.
2. **Ranking**: `prospect_service.compute_priority()` scores each prospect from rating,
   review count, and presence of a website/phone — deliberately a transparent weighted
   formula (see `config.py` for the weights), not ML, so it's easy to explain and retune
   once real call outcomes exist.
3. **Agent 2 — Researcher** (`research_service.py` + `prospect_tasks.py`'s
   `research_prospect`, auto-chained after discovery for any prospect still `pending`):
   builds a `CompanyResearch` knowledge base per prospect, written via
   `prospect_service.mark_research_*()`. Tracked on `Prospect.research_status`
   (`pending -> running -> ready | failed`), independent of `Prospect.outreach_status`
   (`not_reached -> reached | callback | do_not_call`), since "have we researched them"
   and "have we called them" are orthogonal.
4. **Script generation** (`script_service.py`): turns a prospect + its research into a
   call script.
5. **Operator surface**: `backend/api/prospects.py` exposes discover/list/research/
   outreach-status, plus `POST /import-csv` (bulk-create from an operator's own list —
   business_name/phone required, city/country/source/niche optional, deduped by
   normalized phone within the tenant) and `GET /stats` (per-status counts, aggregated
   in SQL so they survive the page limit). `frontend/src/app/prospects/page.tsx` is the
   UI — thin/presentational per FRONTEND.md, with fetching in `hooks/useProspects.ts`
   and the domain UI in `components/features/prospects/`. Results group Country ->
   Category -> City (client-side, over whatever `/prospects` returned, capped at 500
   rows to keep group counts accurate — see `useProspects.ts`'s comment) via
   `lib/prospectGrouping.ts`, with `?q=&where=&country=&category=&city=` URL params
   persisting the search terms and filters across a refresh — the first page in this
   repo to use `useSearchParams`/`useRouter` for filter state, so it's the pattern to
   copy for the next one. City-autocomplete for the "Where" field
   (`hooks/useCityAutocomplete.ts` + `components/features/prospects/CityAutocomplete.tsx`)
   proxies `GET /prospects/city-autocomplete` — see below. The operator's only job in
   this pipeline is deciding who to call and when — discovery and research run
   unattended.

   `Prospect.prospect_notes` (nullable text) is the operator's hand-written context,
   injected as an `[OPERATOR NOTES]` block *after* the researched `[COMPANY BRIEF]` and
   described to the model as outranking it — a human who just spoke to the company knows
   things the scraper doesn't. Unlike `research`, it survives a research re-run. Edited
   inline on /prospects via `PATCH /{id}` (which keys off `model_fields_set`, so an
   explicit null clears the notes rather than reading as "not supplied").

   `Prospect.city`/`.country` are structured fields sourced from Google Places'
   `addressComponents` (`places_service._extract_city_country`), not parsed out of the
   formatted `address` string — component order varies by country, and a UK address
   commonly tags its town `postal_town` with no `locality` at all, which the extractor
   falls back to. `Prospect.source_location` similarly captures the *where* half of the
   discovery search that found a row (`source_query` already captured the *what*) —
   previously silently dropped after being sent to Google. Both are populated going
   forward automatically; existing rows need `scripts/backfill_prospect_city_country.py`
   (an id-exact Place Details lookup per row, never a re-run of the text search, which
   could match a different business).

   `POST /{id}/sandbox-chat` is a text-only sandbox for one prospect: both it and
   `/call` build the personalized prompt through the single
   `api/prospects._build_personalized_prompt()` helper (which itself calls only
   `script_service.build_prospect_prompt`), and `sandbox_service.chat()` — the same
   stateless text-chat mechanism `/api/agents/{id}/sandbox-chat` uses — returns that
   exact `system_prompt` back in the response, so what the operator reads while
   testing is provably what the real call would say, without telephony or touching
   outreach counters. `frontend/src/app/prospects/[id]/sandbox/page.tsx` is the UI
   (fetching lives in `hooks/useProspectSandbox.ts`; chat transcript and the
   agent/model/"what's injected" panel are `components/features/prospects/SandboxChat.tsx`
   and `SandboxContextPanel.tsx`, the latter showing the literal last-turn
   `system_prompt` in a collapsible `<details>`); unlike the agent-level sandbox, the
   prompt isn't editable there (it's built from the prospect's research/notes, and
   that's the point) and every agent is selectable regardless of platform, since
   nothing here dials a phone.

   **Per-call personalized prompts.** `place_test_call(system_prompt_override=...)` is
   how a prospect or lead call swaps in a personalized script for one call without
   overwriting `Agent.system_prompt` — the campaign script stays the source of truth.
   The two engines deliver it by different routes, because they have different places
   to put it:
   - **Hosted LLM** — pushed to Retell's own LLM at provisioning time
     (`_provision_hosted_llm_agent` passes it to `adapter.create_llm/update_llm`).
     Nothing is stored on the Call row; Retell already has the prompt.
   - **Custom LLM** — our websocket answers, and Retell's frames carry only `call_id`,
     so there is no channel to hand the socket a call-scoped prompt. It's persisted to
     `Call.system_prompt_override` at `create_outbound_call_record` time, and
     `api/retell_ws.py` prefers it over `Agent.system_prompt` on the same
     `get_call_by_external_id` lookup it already does to resolve tenant/agent. The
     provisioned Retell agent stays generic, so no per-prospect re-provisioning is
     needed and one Retell agent serves personalized and plain calls alike.

   Null on the Call row means "no personalization" — plain test calls and any hosted-LLM
   call — and the websocket falls back to the agent's saved script.

   `GET /city-autocomplete` proxies Google's Places Autocomplete (New) — type-ahead for
   the discovery "Where" field, debounced client-side with a per-session token for
   Google's session-based Autocomplete billing SKU (distinct from Text Search's). The
   API key never reaches the browser (ADR-002 discipline); a short-input guard rejects
   anything under 2 characters before it ever reaches Google, in case the frontend's own
   debounce is bypassed. Global for now, not narrowed by country — see `region_code`'s
   unused-but-plumbed-through param if that's ever needed.

   **2026-08-21 correction — the paragraph that used to be here was wrong.**
   `POST /import-csv` chains `research_prospect.delay()` per imported row (same as
   discovery) and has since the endpoint was added; a CSV import does reach `ready`.
   That stale claim survived two full sessions of work in this file before being
   caught, including misleading a fix attempt into thinking a chain needed adding when
   the actual bug was elsewhere (below) — a reminder to verify a doc's claim against
   the code before building on it, not just when something looks surprising.

   **What was actually true**, diagnosed the same day from 14 real stuck prospects: a
   `.delay()` call only enqueues a message onto Redis. With no worker running to
   consume it — or one that was running and got restarted, or a non-persistent dev
   Redis that lost the message on its own restart — the row is stuck `pending` forever
   with no code path left that will ever revisit it. `research_prospect` itself can't
   self-heal this: it only runs once dispatched, and dispatch is exactly what didn't
   happen. `prospect_tasks.sweep_stale_prospects` (mirroring `sweep_stale_leads`,
   ADR-011) is the backstop — a Celery Beat tick every 5 minutes re-dispatches any
   prospect whose `research_status` is `pending`/`running` and whose `updated_at` is
   older than `settings.prospect_stale_research_minutes` (20). Re-running is safe for
   both states: `_research()` only reads `name`/`website`/`address` off the row, so a
   second attempt is exactly as safe as the first, just later. Needs
   `celery -A backend.workers.celery_app beat` actually running alongside the worker —
   see CLAUDE.md's Commands section — or the sweep itself never fires either.

   The frontend has its own half of this: `useProspects`' 4s poll (while any row is
   `pending`/`running`) used to run forever if research never resolved, hitting the
   shared database from an open tab nobody was watching. It now gives up after
   `POLL_TIMEOUT_MS` (25 minutes — a slight cushion past the backend's own 20-minute
   cutoff, so a row about to be swept isn't given up on client-side first). This is a
   backstop for the browser, not a fix for the underlying stall; the sweep above is.

   The UI's "Call" button was never actually gated on `research_status` for every
   agent — see ADR-012's dial-a-platform-agent path, added the day before this
   correction, which doesn't need `ready` at all since it injects no research.

**Two overlapping outreach axes — a deliberate deferral, not an oversight.**
`Prospect` now also carries `status` (`not_called | called | booked | flagged |
no_answer | do_not_call`), the operator-set campaign-outcome axis behind the
/prospects dropdown and counts strip. It overlaps `outreach_status` heavily
(`not_called`≈`not_reached`, `called`≈`reached`, `do_not_call` identical) but is
**not** auto-synced with it: `record_call()` (at dispatch) advances only
`outreach_status`, and setting one via `PATCH /api/prospects/{id}` never moves the other.

`status` *is* now advanced automatically too, off a call's terminal state. The per-call
verdict lives in one pure function, `prospect_service.outcome_status_for_call()`, and
two callers consume it:

- `classify_call_outcome()` — from `call_service._fanout_post_call` once a prospect's
  call reaches terminal state (same seam `lead_service.evaluate_call_outcome` hangs off,
  ADR-011). **Forward-only** along `not_called → no_answer → voicemail → called →
  flagged` (`_OUTCOME_STATUS_ORDER`), because it sees one call and can be handed a
  partial view of it.
- `resync_status_from_calls()` — from `call_service.resync_prospects_from_calls`, the
  settle-up step after a platform backfill. Takes a prospect's **entire** call history
  and sets status to the *best* outcome across all attempts. Deliberately **not**
  forward-only: with every call in hand there's no ordering to protect, so it can move a
  status back down — which is what repaired every prospect the per-call path
  misclassified before the `voicemail` rung existed.

`voicemail` sits above `no_answer` (line's live, machine picked up) and is checked
*before* `answered_by_human` — an answering-machine greeting transcribes as a caller
turn, so `answered_by_human` is True for voicemails and testing it first put a whole
campaign of voicemails in `called`. `Call.disconnection_reason ∈ {voicemail_reached,
machine_detected}` is Retell's own machine-detection verdict and is authoritative.
"Rejected" (→ `flagged`) = a human actually spoke *and* post-call sentiment was negative.

`lead_service.evaluate_call_outcome` is **not** affected by that voicemail subtlety: it
gates success on `Call.status ∈ {resolved, escalated}`, and `voicemail_reached` maps to
`failed` via `_FAILURE_REASONS` — so a voicemail is already a failed attempt there.

Adding a parallel column was chosen over widening `outreach_status`'s value set
because the latter is load-bearing for step 3 above (`record_call`'s auto-transition),
the list filter, and the frontend's `OUTREACH_META` — changing its domain is a
breaking change to a documented axis, whereas a new column is purely additive.
That makes it safe, not right: **collapsing these two into one field is an open
design decision**, and until it's made, "have we called them" has two answers.
Anything reading outreach state should know which axis it's reading and why.

Tenant-scoping note: `prospect_service.get_prospect()` is tenant-filtered like everything
else, but Celery tasks have no HTTP caller to scope to, so they use the explicitly-named
`get_prospect_unscoped()` instead — the safe name stays the default, the unsafe one is
opt-in and explicit.

Async-in-Celery hazard: with `CELERY_TASK_ALWAYS_EAGER=true` (solo-dev mode, see RUN.md),
`.delay()` runs the task body inline, and if that call originates from an async FastAPI
route (as `api/prospects.py` does), a plain `asyncio.run()` inside the task would raise
"cannot be called from a running event loop." `prospect_tasks._run_sync()` detects this
and runs the coroutine on a separate thread instead. The same pattern exists (unguarded)
in `transcript_tasks.py` — worth fixing there too if it bites.

### ADR-011: Lead retry scheduler (Bark.com and other warm leads)

Prospects (ADR-006) are discovered and researched by our own pipeline. Leads
(`backend/models/lead.py`) are the other direction: warm inbound leads (Bark.com quote
requests, eventually other sources) that the operator types in by hand — no scraping,
no research phase. What Leads need instead is a call-until-someone-answers scheduler,
which Prospects never had.

**A separate table, not a Prospect with `source="bark"`.** Considered and rejected:
Prospect already carries `research_status`/`outreach_status`/`status`, none of which
fit a hand-entered warm lead, and a Bark lead has no `google_place_id` identity to key
on. Bolting retry-scheduler columns onto Prospect would give every Places-sourced row
unused `retry_state`/`attempt_count`/`next_attempt_at` columns and vice versa. The
call-placement plumbing is still shared (see below) — only the row shape differs.

**Two independent axes, deliberately kept apart from day one** (contrast Prospect's
`status`/`outreach_status`, which drifted into overlap by accretion — see ADR-006's
"two overlapping outreach axes" note):
- `retry_state` (`paused -> scheduled -> in_flight -> succeeded | exhausted`, or
  `do_not_call` from any state) — drives the scheduler. Set only by lead_service's
  state-transition functions, never written directly by a PATCH.
- `status` (`new | contacted | booked | not_interested | unreachable`) — the
  operator-facing campaign outcome, same idea as `Prospect.status`.

**Created paused, armed explicitly.** `POST /api/leads` always lands `retry_state
="paused"`; the scheduler only picks up a lead after `POST /{id}/start`. Auto-arming on
create was considered and rejected — a lead entered with a typo'd phone number or
before the operator has finished writing notes would otherwise start dialing
immediately.

**Prompt assembly reuses the call path, not the research pipeline.** There is no
`CompanyResearch` for a lead (nothing was scraped), so `script_service.build_lead_prompt`
is a sibling to `build_prospect_prompt`, not a repurposing of it: it injects a
`[LEAD DETAILS]` block (source, service requested, budget, city/country, the caller's
own request text, and anything in the generic `details` JSON) plus the operator's
`notes` as `[OPERATOR NOTES]`, same "notes win" convention as prospects. Everything
below the prompt is the *same* code Prospects use — `test_call_service.place_test_call`
gained an optional `lead_id` param (threaded through to `Call.lead_id`) rather than a
parallel dispatch path, so provisioning, streaming, ledger de-duplication (ADR-009),
and webhook handling are identical for a lead call and a prospect call. Both engines
carry the personalized prompt (see "Per-call personalized prompts" below), so a lead or
prospect can be called through a hosted-LLM *or* a custom-LLM agent.

**Outcome isn't known at dispatch time — it arrives on the webhook.** Placing a call
just flips `retry_state` to `in_flight` and increments `attempt_count`; whether it
counts as a success is decided later, when Retell says the call ended.
`call_service.apply_retell_call_state`'s three callers (`handle_call_ended`,
`handle_call_analyzed`, `reconcile_call` — the single writer ADR-007 established) each
now call a `_fanout_post_call(db, call)` once the call reaches a terminal status
(named `_maybe_advance_lead` when ADR-011 landed; `_fanout_lead_post_call` in phase5
Session 1; renamed again once prospect classification joined it — see the note at the
end of this ADR), which hands off to `lead_service.evaluate_call_outcome` if
`Call.lead_id` is set (and to `prospect_service.classify_call_outcome` if
`Call.prospect_id` is — ADR-006). This
piggybacks on the *existing* self-healing path rather than adding a second one: a
webhook that never arrives is already covered by reconciliation, and the lead scheduler
gets that resilience for free.

"Success" is defined as **the call reaching `resolved`/`escalated` status AND at least
one `caller`-role transcript turn** — a voicemail pickup or instant hangup produces
`resolved` with zero caller turns and is treated as a failed attempt, not a success,
per the operator's own bar ("human answered and talked"). `evaluate_call_outcome` is
guarded on `retry_state == "in_flight"`, which does two jobs at once: it makes the
function safe to call twice for the same call (`call_ended` then `call_analyzed` both
reach a terminal status and both call it — the first flips the state, the second is a
no-op), and it means an operator who paused or do-not-called a lead while its call was
still ringing is respected rather than silently re-armed by the call's late outcome.

**Backoff ladder**: 1h → 3h → next 09:00 → next 14:00 → +1 day, capped at
`settings.lead_max_attempts` (5) before the lead is marked `exhausted` for manual
review. Every computed slot is snapped into Mon-Fri
`lead_business_hours_start..lead_business_hours_end` in the lead's own timezone
(`Lead.timezone`, falling back to `settings.default_lead_timezone` — no timezone
derivation from city/country; the operator sets it explicitly or accepts the default).
A dispatch that never reaches `_dispatch` at all (no agent assigned, no phone, or a
`TestCallError` raised before the call is placed) still consumes an attempt against the
cap — `dispatch_scheduled` increments `attempt_count` itself in those branches, since
`advance_after_failure` (shared with the placed-and-failed path) does not increment on
its own, to avoid double-counting a call `_dispatch` already counted.

**Scheduling runs on a clock, not an event** — `backend/workers/lead_tasks.py`'s
`dispatch_due_leads` (Celery Beat, every 5 minutes, `celery_app.py`'s `beat_schedule`)
claims `scheduled` leads whose `next_attempt_at` has passed. A tick that runs after
downtime can find a due slot that's since rolled past business hours (e.g. the beat
process was down overnight); it reschedules to the next valid window without spending
an attempt, rather than dialing at 2am or burning a retry on nothing the lead did
wrong. Celery Beat is a separate process from the worker (a worker alone never reads
`beat_schedule`) — see CLAUDE.md's Commands and docker-compose.yml's new `beat` service.

**Stale in-flight sweep**, same task file, same cadence: a lead stuck `in_flight` past
`settings.lead_stale_in_flight_minutes` (20) means either a genuinely long call (the
sweep is then a no-op — `call_service.reconcile_call` reports "still ongoing" and
nothing changes) or a lost webhook (ADR-007's exact scenario), reusing that existing
reconcile path rather than inventing a second one. If reconciling brings the call to a
terminal status, the same `_fanout_post_call` hook that call_service's webhook
handlers use fires automatically — the sweep's only job is to trigger reconciliation
for leads old enough that Retell should have concluded them by now.

**2026-08-17 — the hook is now a fanout point, and that's deliberately load-bearing.**
`_maybe_advance_lead` did one thing, so it was named after it. phase5 gives the same
terminal-state moment two more consumers (a CRM push, and NDA intent extraction), so it
was renamed `_fanout_lead_post_call`: the name now describes the seam rather than one of
its consumers. (Renamed once more to `_fanout_post_call` when ADR-006's prospect
classification became a consumer too — the seam isn't lead-specific.)

Everything hung off that point inherits reconciliation's self-healing for free — which is
the whole reason it's the right seam and not the webhook handler. A consumer added here
does not need its own recovery path for a webhook that never arrives, because
`reconcile_call` reaches the same function. Two constraints for anything added:
*enqueue, never execute* (this runs on the webhook's <200ms budget, ADR-005), and *assume
it runs more than once per call* — `call_ended`, `call_analyzed` and a later reconcile can
all reach a terminal status, so each consumer needs its own idempotency guard the way
`evaluate_call_outcome` has its `in_flight` check.

### ADR-012: Dialing a platform-native agent (one we didn't build)

Every outbound path above shares an assumption: the agent being dialed is an `Agent` row
*we* own and provision. `place_test_call` always creates or updates the Retell agent
before dialing it, caching the platform ids on `Agent.voice_config`. An agent built by
hand in Retell's own dashboard was therefore unreachable from this dashboard — the
operator had to leave and dial from Retell's UI.

`place_platform_agent_call` is the second source. The split is exactly one question:
**do we own this agent's configuration?**

| | Local agent (`place_test_call`) | Platform-native (`place_platform_agent_call`) |
|---|---|---|
| Agent record | our `Agent` row | none — only the platform's id |
| Provisioning | we create/update it every call | none at all |
| Prompt | ours (`Agent.system_prompt`, personalizable per call) | theirs, fixed in the dashboard |
| Personalization | whole prompt rewritten per call (brief + notes) | values for the `{{placeholders}}` their script declares (ADR-012a) |
| Brain | Retell's hosted LLM, or ours via `retell_ws.py` | whatever the dashboard says |
| Tools | server-side (ADR-003) on the custom-LLM path | not ours |
| We contribute | everything | the from-number and the dial |

**The roster is fetched live, never mirrored.** `GET /api/agents/platform` proxies
`RetellAdapter.list_platform_agents` on every request. An import step would let the
picker offer an agent that was since renamed, re-voiced or deleted upstream — and there
is no webhook telling us when that happens, so a mirror could only ever be stale in a way
that costs a wasted call. Two normalizations happen in the adapter, both from the real
API's shape: `list-agents` returns one entry *per agent version* (we keep the highest per
id, since that's what `override_agent_id` dials), and `response_engine` is flattened to a
bare `engine` string so the UI can show whether an agent runs on Retell's own brain.

**The id is validated against that roster before dialing.** A typo'd or deleted id would
otherwise surface as an opaque Retell 4xx after the request was already spent — and it's
the one guard stopping a raw client-supplied id from reaching the platform API unchecked.

**`Call.agent_id` is now nullable, with `external_agent_id` alongside it.** The
alternative — not recording these calls at all — would make half an operator's calls
invisible to their own dashboard, which defeats the point of dialing from it.
`create_outbound_call_record` enforces that exactly one of the two is set: neither makes
the row unattributable, both makes "which agent ran this call" ambiguous for every reader
downstream. Enforced in the service rather than the database because it's a programming
error, not user input, and should fail at the call site.

**Both dial surfaces offer both sources, but they are not interchangeable on the
prospects page.** `POST /api/prospects/{id}/call` takes exactly one of `agent_id` /
`external_agent_id` (a `model_validator` on `ProspectCallRequest` — neither leaves nobody
to dial with, both makes it ambiguous which script runs). The difference is the whole
point of that page: a local agent gets this prospect's `[COMPANY BRIEF]` +
`[OPERATOR NOTES]` injected for the call, and a platform-native one receives none of that
— only values for the `{{placeholders}}` its own script declares (ADR-012a), prefilled
from the prospect and editable before dialing. The picker groups the two under labelled
`<optgroup>`s and the panel warns explicitly when a platform agent is selected, because
an operator staring at a knowledge base will otherwise assume it was sent.

The research-ready gate therefore applies only to the personalized path. It exists
because the prompt needs the brief; with nothing to inject there is nothing to wait for.
A useful side effect: a CSV-imported prospect — which never reaches `research_status
"ready"` (see ADR-006) — is now dialable through a platform agent, closing half of that
open follow-up. The `Call` button on `ProspectRow` is no longer gated on research for the
same reason; `Sandbox chat` still is, since it has nothing to show without a brief.

Two consequences follow from not owning the agent, and both are real:
- **Lifecycle webhooks only arrive if the operator sets our `/webhooks/retell` URL on
  that agent in Retell's dashboard.** We can't stamp `webhook_url` at provisioning time
  the way ADR-005 describes, because we don't provision. Without it the row sits
  `in_progress` until `POST /api/calls/sync` reconciles it from the platform — that path
  needs only `external_id`, so ADR-007's self-healing covers this for free.
- **No whole-prompt personalization.** `system_prompt_override` has nowhere to go: the
  platform's agent holds the script, and neither delivery route from ADR-006 exists here.
  Dynamic variables (below) are the narrower channel that does work.

**ADR-012a, 2026-08-20 — dynamic variables are the personalization channel, and the
paragraph above used to say there wasn't one.** That was wrong. Retell substitutes
`{{placeholder}}` tokens in an agent's prompt from a `retell_llm_dynamic_variables` map
passed on `create-phone-call`, so a dashboard-built agent *can* be told who it is calling
— it just receives values for slots its author left, rather than a rewritten script.

**There is no endpoint that reports an agent's placeholders.** Retell's dashboard derives
its "Dynamic Variables" fill-in list by scanning the prompt, and
`RetellAdapter.get_agent_dynamic_variables` does the same (`_DYNAMIC_VARIABLE_RE` over
`general_prompt` + `begin_message`, after resolving the agent's `llm_id`). Verified by
probing the real account: the four names the dashboard offered for "Roofing Agent Test
Case #1" — `company_name`, `contact_name`, `current_time`, `user_number` — are exactly
what the regex finds. `begin_message` is scanned too, since an opener is where an
unfilled placeholder gets spoken first. An agent whose prompt we can't read (`custom-llm`,
`conversation-flow`) returns `[]` rather than raising: not knowing must not block a dial
that may need nothing.

**An unfilled placeholder is not a no-op — Retell leaves the literal `{{company_name}}`
in the prompt and the agent reads it aloud to a real prospect.** So
`place_platform_agent_call` refuses to dial when any declared name is missing or blank,
and both UIs disable the call button with the specific names listed. Blocking beats
spending a real call on that. Values not declared by the prompt are dropped rather than
forwarded — harmless to Retell, but they would make the audit trail read as though the
agent used data it never saw.

Suggested values on the prospects page come from `lib/dynamicVariables.ts` — a
convention map (`company_name`/`companyName`/`business_name` → the prospect's name, and
so on, matched case- and separator-insensitively). Since the names are whatever the
prompt's author typed, nothing can be guaranteed: every suggestion lands in an **editable
field the operator can read before dialing**, never straight into the request. A wrong
guess spoken to a real prospect is worse than a blank box.

This narrows but does not close the gap with a local agent. A local agent gets the whole
researched brief; a platform agent gets values for the slots its script already has. If
the dashboard prompt has no `{{company_name}}`, no amount of data on our side reaches it.

`retell_ws.py` refuses a connection for a call with no `agent_id` explicitly. That's
reachable — an operator can point a dashboard-built agent's custom-LLM websocket at our
tunnel — and it has no prompt, model or `ToolConfig` rows to answer with.

**Known gap: `RETELL_API_KEY` is one global env var, not per-tenant**, so the roster and
the account it dials from are shared by every tenant. `list_platform_agents` takes no
tenant for that reason rather than pretending to scope. This is the first surface where
that bites visibly (tenant A sees tenant B's agent names), and it needs to move into
`Integration` (per-tenant credential storage already exists, phase5 S1) before a second
customer exists.
