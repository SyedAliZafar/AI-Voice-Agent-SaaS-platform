# CONTEXT.md — AI Voice Agent SaaS Platform

> **Investigation logs:** [phase0.md](phase0.md), [phase2.md](phase2.md) and
> [phase3.md](phase3.md) document real de-risking and bug-fixing work (auth rewrite,
> telephony proof, latency spike, call-lifecycle fixes) done after this file was first
> written. Where they contradict an ADR below, they supersede it — this file has been
> updated to match, but if something still looks off, trust the phase docs and the code
> over this one, and fix this file. **phase3.md is the current state of play**, including
> what is verified vs. merely written.

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
│   │   ├── prospects.py          # Prospecting pipeline: discover/list/research/outreach status
│   │   ├── webhooks.py           # POST /webhooks/retell, POST /webhooks/vapi
│   │   ├── ws.py                 # WebSocket endpoint for live call streaming (dashboard-facing)
│   │   └── retell_ws.py          # Retell Custom LLM WebSocket (in progress — see phase0.md)
│   │
│   ├── services/                 # Business logic (no HTTP concerns)
│   │   ├── __init__.py
│   │   ├── agent_service.py      # Agent CRUD, prompt management
│   │   ├── call_service.py       # Call lifecycle, state machine
│   │   ├── test_call_service.py  # Places a call via the voice platform's hosted LLM (smoke test only — no configured model/tools, see phase0.md)
│   │   ├── voice_platform.py     # Abstract base for Retell/Vapi adapters
│   │   ├── retell_adapter.py     # Retell AI specific implementation
│   │   ├── vapi_adapter.py       # Vapi AI specific implementation
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
│   │   # get_current_tenant dependency. See ADR-001 and phase0.md Task 2.
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
for WebSocket scopes, which matters for the Retell custom-LLM socket. See `phase0.md`
Task 2 for the full audit that drove this.

`/webhooks/*` are the deliberate exception: Retell/Vapi can't send our JWT, so those
routes stay unauthenticated by this mechanism. They still lack platform signature
verification — a known open gap, see `backend/api/webhooks.py` and `phase0.md`.

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

### ADR-004: WebSocket for live call monitoring
The dashboard's live call view uses WebSocket (not SSE) because we need bidirectional:
the operator can barge-in, whisper, or force-transfer. Redis PubSub distributes call
events from the webhook handler to all connected WebSocket clients watching that call.

### ADR-005: Celery for post-call processing
Transcript analysis, sentiment scoring, metric rollups, and CRM sync all happen async
after the call ends. The webhook handler enqueues tasks and returns 200 immediately.
This keeps webhook response time under 200ms (voice platforms timeout at 5-10s).

**Retell's webhook contract** (learned the hard way — see phase3.md): exactly three
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

### ADR-008: Provider-agnostic LLM, chosen per agent
`llm_service.py` was hardcoded to one module-level `AsyncOpenAI(base_url="https://api.deepseek.com")`
— trying GPT meant editing that file. DeepSeek and OpenAI both speak the OpenAI-compatible
chat-completions protocol, so "which provider" reduces to `api_key` + `base_url` + `model`:

- A model id resolves to a provider via `MODEL_CATALOG` (the UI's dropdown source) or,
  for an id not yet listed, a prefix guess (`gpt-*`/`o1*`/`o3*` -> openai, `deepseek-*` ->
  deepseek) — `llm_service.provider_for()`. Unresolvable, or resolvable but missing its
  API key, both raise `LLMConfigError` rather than a raw SDK error.
- Exactly one `AsyncOpenAI` client per provider, cached (`get_client`, `@lru_cache`) — not
  per call. phase0.md measured ~2.5s of dead air on a cold client (DNS + TLS); constructing
  one per turn in the WS handler would reintroduce that on every response.
- `Agent.llm_model` (empty string = "use `settings.default_llm_model`") makes the choice
  per-agent, not global — set via the "Conversation engine" card's model `<select>`
  (`GET /api/agents/models` reports the catalog plus which providers are `configured`).
  Only takes effect on the `use_custom_llm` path; Retell's hosted LLM ignores it.
- `get_agent_response(..., tools_enabled=...)` — `False` omits the `tools` kwarg entirely
  (not `tools=None`; the SDK's `tools` param isn't `Optional`, so `None` would literally
  serialize as `"tools": null`). This is what lets the sandbox (below) run a text chat
  without risking a real `book_appointment`/`create_lead` call.

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
   outreach-status; `frontend/src/app/prospects/page.tsx` is the UI. The operator's only
   job in this pipeline is deciding who to call and when — discovery and research run
   unattended.

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
- LLM failures fall back to a static "I'm having trouble, let me transfer you" response

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

## What NOT to build (for now)
- Custom STT/TTS — use the voice platform's built-in. Don't reinvent.
- Real-time audio streaming in the browser — too complex, use Retell's built-in monitoring
- Multi-language support — get English working perfectly first
- A/B testing of prompts — track it manually in v1, build tooling in v2
- Billing/subscriptions — use Stripe Checkout, don't build a billing engine
