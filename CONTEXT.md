# CONTEXT.md — AI Voice Agent SaaS Platform

> **Investigation logs:** [phase0.md](phases/completed/phase0.md),
> [phase2.md](phases/completed/phase2.md) and [phase3.md](phases/completed/phase3.md) document real
> de-risking and bug-fixing work (auth rewrite, telephony proof, latency spike,
> call-lifecycle fixes) done after this file was first written. Where they contradict an
> ADR below, they supersede it — this file has been updated to match, but if something
> still looks off, trust the phase docs and the code over this one, and fix this file.
> **[phase3.md](phases/completed/phase3.md) is the current state of play**, including
> what is verified vs. merely written.
>
> Phase docs live under [phases/](phases/): `completed/` for finished work,
> `in-progress/` for work still open. A phase doc moves to `completed/` only once every
> session in it is both done *and* real-call verified.

## Project overview

Multi-tenant SaaS platform for building, deploying, and managing AI voice agents.
Integrates with Retell AI and Vapi AI as voice platforms, uses DeepSeek as the LLM brain,
and exposes a dashboard for real-time call monitoring, analytics, and agent configuration.

## Tech stack

| Layer | Technology | Why |
|-------|-----------|-----|
| Backend API | FastAPI (Python 3.12+) | Async-first, WebSocket support, auto-docs |
| Task queue | Celery + Redis | Async webhook processing, transcript analysis |
| Database | PostgreSQL 16 + SQLAlchemy 2.0 | Multi-tenant, JSONB for flexible configs |
| Cache / PubSub | Redis 7 | Session state, real-time call event broadcasting |
| Object storage | S3 / MinIO | Call recordings, transcript exports |
| Frontend | Next.js 14 + React 18 + Tailwind | SSR dashboard, WebSocket live call view |
| Voice platforms | Retell AI SDK, Vapi AI SDK | Telephony, STT/TTS, call orchestration |
| LLM | DeepSeek + OpenAI (both OpenAI-compatible), per-agent (ADR-008) | Conversation engine, intent detection, function calling |
| Auth | Clerk or Auth0 | Multi-tenant auth with org-level roles |
| Infra | Docker Compose (dev), AWS ECS (prod) | Container-first deployment |

## Project structure

```
voiceagent/
├── CONTEXT.md                    # You are here
├── pyproject.toml                # Python deps (uv/poetry)
├── docker-compose.yml            # Local dev: postgres, redis, minio, api, worker
├── .env.example                  # Required env vars template
│
├── phases/                       # Investigation/remediation logs (see note at top)
│   ├── completed/                # Done AND real-call verified
│   │   ├── phase0.md             # De-risking gates before the Custom LLM WS migration
│   │   ├── phase2.md             # Outbound test call: from-number setup
│   │   └── phase3.md             # Call lifecycle correctness + reaching DeepSeek
│   └── in-progress/              # Still open — promote only when fully verified
│       ├── phase4.md             # Remediation queue (Sessions 1-11)
│       ├── outliers.md           # Real-call findings feeding phase4
│       ├── session5.md           # Session 5 handoff (has an open "what's left" list)
│       └── promptstotest.md      # Prompts pending a real-call verification pass
│
├── backend/
│   ├── main.py                   # FastAPI app factory
│   ├── config.py                 # Pydantic Settings (env-based config)
│   ├── database.py               # SQLAlchemy engine, session factory
│   │
│   ├── models/                   # SQLAlchemy ORM models
│   │   ├── __init__.py
│   │   ├── tenant.py             # Tenant, User
│   │   ├── agent.py              # Agent, PhoneNumber, ToolConfig
│   │   ├── call.py               # Call, CallEvent, Transcript
│   │   ├── prospect.py           # Prospect — Prospector/Researcher pipeline (see ADR-006)
│   │   └── base.py               # DeclarativeBase, TenantMixin, TimestampMixin, UUIDMixin
│   │
│   ├── schemas/                  # Pydantic request/response schemas
│   │   ├── __init__.py
│   │   ├── agent.py
│   │   ├── call.py
│   │   ├── prospect.py
│   │   └── webhook.py
│   │
│   ├── api/                      # FastAPI routers
│   │   ├── __init__.py
│   │   ├── deps.py               # get_current_tenant — the tenant-scoping dependency (ADR-001)
│   │   ├── agents.py             # CRUD for agents + prompt config
│   │   ├── calls.py              # Call history, transcript retrieval
│   │   ├── analytics.py          # Metrics, aggregations
│   │   ├── prospects.py          # Prospecting pipeline: discover/import-csv/list/stats/research/status
│   │   ├── webhooks.py           # POST /webhooks/retell, POST /webhooks/vapi
│   │   ├── ws.py                 # WebSocket endpoint for live call streaming (dashboard-facing)
│   │   └── retell_ws.py          # Retell Custom LLM WebSocket (in progress — see phases/completed/phase0.md)
│   │
│   ├── services/                 # Business logic (no HTTP concerns)
│   │   ├── __init__.py
│   │   ├── agent_service.py      # Agent CRUD, prompt management
│   │   ├── call_service.py       # Call lifecycle, state machine
│   │   ├── test_call_service.py  # Places a call via the voice platform's hosted LLM (smoke test only — no configured model/tools, see phases/completed/phase0.md)
│   │   ├── voice_platform.py     # Abstract base for Retell/Vapi adapters
│   │   ├── retell_adapter.py     # Retell AI specific implementation
│   │   ├── vapi_adapter.py       # Vapi AI specific implementation
│   │   ├── tunnel_check.py       # PUBLIC_BASE_URL reachability probe, shared by the custom-LLM preflight guard and scripts/check_custom_llm.py
│   │   ├── public_url.py         # Resolves PUBLIC_BASE_URL; "auto" discovers the live quick-tunnel host from cloudflared (ADR-007)
│   │   ├── llm_service.py        # Provider-agnostic LLM calls (DeepSeek/OpenAI, ADR-008), tool execution
│   │   ├── sandbox_service.py    # Text-chat agent testing sandbox — no phone call, see "Agent testing sandbox" flow
│   │   ├── integration_service.py # CRM, calendar, custom webhook integrations
│   │   ├── analytics_service.py  # Metrics computation, sentiment aggregation
│   │   ├── places_service.py     # Google Places search — prospecting Agent 1, discovery (ADR-006)
│   │   ├── research_service.py   # Company research — prospecting Agent 2, knowledge base (ADR-006)
│   │   ├── script_service.py     # Call-script generation for prospects
│   │   └── prospect_service.py   # Prospect CRUD, upsert-from-places, priority ranking (ADR-006)
│   │
│   ├── tools/                    # LLM function-calling tool definitions
│   │   ├── __init__.py
│   │   ├── base.py               # BaseTool abstract class
│   │   ├── book_appointment.py
│   │   ├── check_availability.py # read-only "is this slot free?" (see ADR-009 note)
│   │   ├── cancel_appointment.py     # (ADR-009 §4c, phases/in-progress/outliers.md §5)
│   │   ├── reschedule_appointment.py # (ADR-009 §4c, phases/in-progress/outliers.md §5)
│   │   ├── lookup_customer.py
│   │   ├── create_lead.py
│   │   ├── transfer_call.py
│   │   └── send_sms.py
│   │
│   ├── workers/                  # Celery tasks
│   │   ├── __init__.py
│   │   ├── celery_app.py         # Celery config
│   │   ├── transcript_tasks.py   # Post-call transcript processing
│   │   ├── analytics_tasks.py    # Periodic metric rollups
│   │   └── prospect_tasks.py     # discover_prospects / research_prospect (ADR-006)
│   │
│   ├── middleware/
│   │   ├── rate_limit.py         # Redis-based rate limiting
│   │   └── logging.py            # Structured JSON logging
│   │   # NOTE: tenant.py used to live here — deleted, superseded by api/deps.py's
│   │   # get_current_tenant dependency. See ADR-001 and phases/completed/phase0.md Task 2.
│   │
│   └── migrations/               # Alembic migrations
│       ├── env.py
│       └── versions/
│
├── frontend/                     # Next.js app
│   ├── package.json
│   ├── src/
│   │   ├── app/
│   │   │   ├── layout.tsx
│   │   │   ├── dashboard/
│   │   │   │   └── page.tsx      # Main dashboard (metrics + recent calls)
│   │   │   ├── agents/
│   │   │   │   ├── page.tsx      # Agent list
│   │   │   │   ├── [id]/
│   │   │   │   │   ├── page.tsx  # Agent detail + prompt editor
│   │   │   │   │   └── sandbox/
│   │   │   │   │       └── page.tsx  # Text-chat sandbox — try the persona, no phone call
│   │   │   │   └── new/
│   │   │   │       └── page.tsx  # Create agent wizard
│   │   │   ├── calls/
│   │   │   │   ├── page.tsx      # Call history with filters
│   │   │   │   ├── [id]/
│   │   │   │   │   └── page.tsx  # Single call detail + transcript
│   │   │   │   └── live/
│   │   │   │       └── page.tsx  # WebSocket live call monitor
│   │   │   ├── prospects/
│   │   │   │   └── page.tsx      # Prospecting pipeline UI (ADR-006)
│   │   │   ├── settings/
│   │   │   │   └── page.tsx      # Integrations, phone numbers, billing
│   │   │   └── api/strategist/
│   │   │       └── route.ts      # Next.js route proxying an LLM call for the agent-builder wizard — see FRONTEND.md
│   │   ├── components/           # Currently flat — see FRONTEND.md for the target components/ui + components/features split
│   │   │   ├── ui.tsx             # De-facto primitives: Button, Card, Badge, PageHeader, EmptyState, Skeleton
│   │   │   ├── form.tsx
│   │   │   ├── AppShell.tsx
│   │   │   ├── Sidebar.tsx
│   │   │   ├── Topbar.tsx
│   │   │   ├── CallTable.tsx
│   │   │   ├── MetricCard.tsx
│   │   │   ├── AgentCard.tsx
│   │   │   ├── AgentBuilder.tsx
│   │   │   ├── Stepper.tsx
│   │   │   ├── TranscriptViewer.tsx
│   │   │   ├── PromptEditor.tsx  # Monaco-based prompt editing
│   │   │   ├── LiveCallPanel.tsx # Real-time call audio + transcript
│   │   │   └── icons.tsx
│   │   ├── hooks/
│   │   │   ├── useWebSocket.ts
│   │   │   └── useCallMetrics.ts
│   │   └── lib/
│   │       ├── api.ts            # Axios wrapper + auth-token interceptor
│   │       ├── types.ts          # Shared TS interfaces, hand-mirrored from backend/schemas/*.py — no codegen, see FRONTEND.md
│   │       ├── format.ts
│   │       ├── builder.ts
│   │       └── constants.ts
│   └── tailwind.config.ts
│
└── tests/
    ├── conftest.py               # Fixtures: test DB, test client, mock voice platform
    ├── test_auth.py              # Every protected route rejects missing/forged tokens; cross-tenant isolation
    ├── test_agents.py
    ├── test_calls.py
    ├── test_call_service.py
    ├── test_test_call_service.py
    ├── test_retell_ws.py
    ├── test_webhooks.py
    ├── test_llm_service.py
    ├── test_sandbox_service.py
    ├── test_prospects.py         # /api/prospects router: validation, tenant scoping, CSV import
    ├── test_prospect_service.py
    ├── test_research_service.py
    ├── test_script_service.py
    └── test_tools/
        ├── test_book_appointment.py
        └── test_lookup_customer.py
```

This tree is a snapshot — it will drift again. When a change adds a new service, router,
worker, or top-level component, update this tree in the same change (see
[EFFICIENCY.md](EFFICIENCY.md)).

## Architecture decisions

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

Status mapping lives there too: `disconnection_reason` distinguishes `resolved` from
`escalated` (`call_transfer`) and `failed` (dial failures, `error*`), which is richer than
the "everything that ended is resolved" assumption this code started with.

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
   business_name/phone required, city/source/niche optional, deduped by normalized phone
   within the tenant) and `GET /stats` (per-status counts, aggregated in SQL so they
   survive the 100-row page limit). `frontend/src/app/prospects/page.tsx` is the UI. The
   operator's only job in this pipeline is deciding who to call and when — discovery and
   research run unattended.

   CSV-imported prospects land with `research_status="pending"` and nothing chained to
   advance them, so they never reach `ready` — which is what the UI's "Call" button
   gates on. Calling an imported prospect from the dashboard therefore doesn't work yet;
   wiring import into `research_prospect` (or relaxing the gate) is an open follow-up.

**Two overlapping outreach axes — a deliberate deferral, not an oversight.**
`Prospect` now also carries `status` (`not_called | called | booked | flagged |
no_answer | do_not_call`), the operator-set campaign-outcome axis behind the
/prospects dropdown and counts strip. It overlaps `outreach_status` heavily
(`not_called`≈`not_reached`, `called`≈`reached`, `do_not_call` identical) but is
**not** auto-synced with it: `record_call()` still advances only `outreach_status`,
and setting one via `PATCH /api/prospects/{id}` never moves the other.

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

## Coding conventions

### Python
- Python 3.12+, type hints everywhere, `ruff` for linting + formatting
- `uv` as package manager (faster than poetry)
- Pydantic v2 for all schemas, `model_validator` over custom `__init__`
- SQLAlchemy 2.0 style (mapped_column, no legacy Query API)
- Every service method is `async def` — we're running on uvicorn with asyncio
- Tests use `pytest-asyncio` + `httpx.AsyncClient`

### Error handling
- All API errors return structured JSON: `{"detail": "...", "code": "AGENT_NOT_FOUND"}`
- Voice platform webhook failures retry 3x with exponential backoff
- LLM failures fall back to a static spoken response in `retell_ws.py`'s
  `response_required`/`reminder_required` handling — `LLMConfigError` (bad model/missing
  key) gets "I'm having trouble, let me transfer you"; any other exception from the
  call (SDK timeout, rate limit, 5xx) is caught separately and gets "I'm having some
  trouble, let me get someone to help you". Both branches log and keep the websocket
  alive — never let an LLM-side failure kill a live call.

### Environment variables (required)
```
DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/voiceagent
REDIS_URL=redis://localhost:6379/0
ANTHROPIC_API_KEY=sk-ant-...
RETELL_API_KEY=...
VAPI_API_KEY=...
TWILIO_ACCOUNT_SID=...
TWILIO_AUTH_TOKEN=...
S3_BUCKET=voiceagent-recordings
CLERK_SECRET_KEY=...
```

The frontend needs its own env file, `frontend/.env.local` (copy from
`frontend/.env.local.example`) — Clerk's publishable key is a separate,
browser-safe key from the backend secret key above:
```
NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=pk_test_...
NEXT_PUBLIC_API_URL=http://localhost:8000/api
```

### Git conventions
- Branch naming: `feat/agent-builder`, `fix/webhook-timeout`, `chore/deps-update`
- Commit messages: conventional commits (`feat:`, `fix:`, `docs:`, `refactor:`)
- PR requires passing CI (ruff, pytest, type check) + 1 review

## Change recipes

The layering here (model → schema → service → api) means even a small change touches
several files. That's the adapter/layer separation working as designed, not accidental
sprawl — but it does mean the blast radius has to be known up front rather than
rediscovered by grepping. This table is that map. Find your change type, touch those
files, stop.

| Change type | Files to touch, in order |
|---|---|
| **Add a field to an existing model** | `models/<x>.py` → `uv run alembic revision --autogenerate` → `schemas/<x>.py` → service layer *only if* logic depends on it → `api/<router>.py` if exposed → its test → `frontend/src/lib/types.ts` if the frontend reads it (hand-synced, see FRONTEND.md) |
| **Add a new LLM tool** | `tools/<name>.py` implementing `BaseTool` → register in `tools/__init__.py`'s `_REGISTRY` (that's the only wiring — `llm_service` reads the registry) → `tests/test_tools/test_<name>.py` |
| **Add a new voice platform** | new `services/<name>_adapter.py` implementing `VoicePlatformAdapter` → add to the `adapters` dict in `voice_platform.py`'s `get_adapter()` → nothing else; existing adapters and call paths are untouched (ADR-002) |
| **Add a new Celery task** | `workers/<x>_tasks.py` (sync entry point + `async def _impl`, mirroring `prospect_tasks.py`) → register the enqueue call site (usually a webhook handler or service) → test with `CELERY_TASK_ALWAYS_EAGER=true`. If the task is async and may be called from an async route, use the `_run_sync()` pattern from `prospect_tasks.py` (see ADR-006). |
| **Add a new API endpoint** | `api/<router>.py` (take `tenant_id: uuid.UUID = Depends(get_current_tenant)` — never a query param) → request/response models in `schemas/<x>.py` → the service method it delegates to → test, including an auth case in `tests/test_auth.py` |
| **Add a new router (new resource)** | all of the above, plus register the router in `main.py`, and **add it to the structure tree in this file** |
| **Add a new service / worker / top-level component** | write it, then update the structure tree in this file in the same change — this is the rule whose absence caused the drift this table exists to prevent |
| **Change voice-platform behavior** | the relevant `*_adapter.py` only. If you find yourself importing the Retell or Vapi SDK anywhere else, stop — that's the ADR-002 violation. |

Two rules that override anything above: never bypass tenant scoping (ADR-001), and never
do real work inline in a webhook handler (ADR-005). See [EFFICIENCY.md](EFFICIENCY.md)
for how to move through these efficiently.

## Key data flows

### Prospecting flow (upstream of everything below)
1. Operator (or a scheduled trigger) calls `POST /api/prospects/discover` with a
   query/location → `discover_prospects` task runs Google Places search, upserts
   `Prospect` rows, computes priority score.
2. Any newly-seen prospect (`research_status="pending"`) is auto-chained into
   `research_prospect` → builds `CompanyResearch`, marks `ready` or `failed`.
3. Operator reviews ranked prospects in `frontend/src/app/prospects/page.tsx`, generates
   a script (`script_service.py`), and decides who becomes a `test-call` / outbound call
   target and when (`outreach_status` moves from `not_reached` onward).

### Inbound call
1. Caller dials → Twilio routes to Retell/Vapi
2. Voice platform does STT → sends text via webhook to `POST /webhooks/retell`
3. Webhook handler creates/updates `Call` record, publishes to Redis PubSub
4. `llm_service.call_claude()` with system prompt + conversation history + available tools
5. DeepSeek responds with text OR a tool call → we execute tool → return result to DeepSeek
6. Final text response sent back to voice platform → TTS → caller hears it
7. Loop continues until hangup or escalation trigger

### Post-call processing (Celery)
1. Call ends → Retell POSTs `call_ended` to the per-agent `webhook_url`
2. `webhooks.py` verifies the signature, resolves the row by `external_id`, and writes
   terminal state (status from `disconnection_reason`, duration from `duration_ms`,
   transcript) via `apply_retell_call_state`
3. Handler enqueues `process_transcript`; `call_analyzed` follows shortly after with
   `call_analysis.user_sentiment`
4. If CRM integration configured, lead/contact created/updated in HubSpot/Salesforce

If step 1 never happens (no tunnel, unset `PUBLIC_BASE_URL`, tunnel restarted mid-call),
`POST /api/calls/sync` reconciles from the platform instead — see ADR-007.

### Agent testing sandbox
Try an agent's persona/system_prompt over text before spending a real call on it —
`frontend/src/app/agents/[id]/sandbox/page.tsx` → `POST /api/agents/{id}/sandbox-chat` →
`sandbox_service.chat()` → `llm_service.get_agent_response()`. Stateless: the client
resends the whole message history each turn, the same shape a live call already uses —
no new table, no session store. Unlike the live custom-LLM path (which rejects
`system_prompt_override` because the WS handler reads `Agent.system_prompt` fresh from
the DB per call), the sandbox can run with an unsaved prompt draft — that's the point of
the feature. Tools default off (`tools_enabled=False`): `book_appointment`/`create_lead`
make real HTTP calls to Cal.com/HubSpot via `integration_service.py`, and a text chat
shouldn't hit those by accident.

## LLM prompt architecture

System prompt per agent follows this structure:
```
[ROLE] You are {agent_name}, a voice assistant for {company_name}.
[GUARDRAILS] Never discuss: {excluded_topics}. Never promise: {restricted_actions}.
[PERSONALITY] Tone: {tone}. Pacing: {pacing}. Max response length: {max_words} words.
[TOOLS] You have access to these functions: {tool_descriptions}.
[ESCALATION] Transfer to human when: {escalation_triggers}.
[CONTEXT] Current time: {now}. Caller number: {caller_number}. Previous interactions: {history}.
```

## Performance targets
- Webhook response: < 200ms (just enqueue + ack)
- LLM round-trip (text in → text out): < 1.5s including tool execution
- WebSocket latency: < 100ms for call event propagation
- Dashboard API: < 300ms for paginated queries
- Concurrent calls per agent: 50+ (limited by voice platform plan)

`llm_service.get_agent_response()`/`stream_agent_response()` take an optional `llm_events`
list; if passed, it appends one `{stage, model, duration_ms, prompt_tokens,
completion_tokens}` sample per `completions.create()` call (`stage` is `"initial"` or
`"tool_followup"`, one per LLM round-trip within a turn) — the streaming path adds
`ttfb_ms`/`streamed` (see ADR-009). `retell_ws.py` passes one in and, after the terminal
response frame is sent, persists the samples via `call_service.record_llm_events()` as
`CallEvent(event_type="llm_timing")` rows — the first real writer of `CallEvent`, which
had been a defined-but-unused model. This was the before/after baseline for ADR-009's
streaming work; `ttfb_ms` (time to first content delta) is now the primary metric against
the LLM round-trip target above, since `duration_ms` (the full round-trip) stays roughly
flat between the two paths by design.

## What NOT to build (for now)
- Custom STT/TTS — use the voice platform's built-in. Don't reinvent.
- Real-time audio streaming in the browser — too complex, use Retell's built-in monitoring
- Multi-language support — get English working perfectly first
- A/B testing of prompts — track it manually in v1, build tooling in v2
- Billing/subscriptions — use Stripe Checkout, don't build a billing engine
