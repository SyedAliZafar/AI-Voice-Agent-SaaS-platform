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
├── CONTEXT.md                    # You are here — architecture, structure, flows, ADR index
├── ADR.md                        # Full architecture-decision write-ups (indexed below)
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
│       ├── phase5.md             # CRM push + post-call NDA dispatch for Leads (Sessions 1-6)
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
│   │   ├── lead.py               # Lead — hand-entered warm leads + retry scheduler state (ADR-011)
│   │   ├── integration.py        # Integration — per-tenant CRM connection (phase5 S1); NOT a ToolConfig row, see its docstring
│   │   ├── nda.py                # NdaDispatch — one NDA per lead call, unique(lead_id, call_id) (phase5 S3)
│   │   └── base.py               # DeclarativeBase, TenantMixin, TimestampMixin, UUIDMixin
│   │
│   ├── schemas/                  # Pydantic request/response schemas
│   │   ├── __init__.py
│   │   ├── agent.py
│   │   ├── call.py
│   │   ├── prospect.py
│   │   ├── lead.py
│   │   ├── integration.py        # + mask_config/mask_secret — responses never echo a stored secret
│   │   ├── nda.py
│   │   ├── phone_number.py       # PlatformPhoneNumber — live platform roster, not persisted
│   │   └── webhook.py
│   │
│   ├── api/                      # FastAPI routers
│   │   ├── __init__.py
│   │   ├── deps.py               # get_current_tenant — the tenant-scoping dependency (ADR-001)
│   │   ├── agents.py             # CRUD for agents + prompt config; GET /platform + POST /platform/call for platform-native agents (ADR-012); GET /templates + POST /from-template for the scripts/agent_templates gallery
│   │   ├── calls.py              # Call history, transcript retrieval, GET /{id}/events (the CallEvent audit trail — tool calls, llm_timing, ivr_hangup)
│   │   ├── phone_numbers.py      # GET /api/phone-numbers — the platform account's number roster, fetched live (same not-mirrored rule as ADR-012's agent roster)
│   │   ├── analytics.py          # Metrics, aggregations
│   │   ├── prospects.py          # Prospecting pipeline: discover/import-csv/list(?status=)/stats/research/status/call/batch-call/sync-calls/export/sandbox-chat/city-autocomplete. /call + /batch-call take agent_id OR external_agent_id — only the former personalizes (ADR-012). /sync-calls backfills the platform's own call history into the ledger
│   │   ├── leads.py              # Bark/warm-lead CRUD + scheduler control (start/pause/do-not-call) + call-now (ADR-011)
│   │   ├── integrations.py       # Connect a tenant's CRM: GET/PUT/DELETE /{kind} + POST /{kind}/test — the repo's first credential CRUD surface
│   │   ├── webhooks.py           # POST /webhooks/retell, POST /webhooks/vapi
│   │   ├── ws.py                 # WebSocket endpoint for live call streaming (dashboard-facing)
│   │   └── retell_ws.py          # Retell Custom LLM WebSocket (in progress — see phases/completed/phase0.md)
│   │
│   ├── services/                 # Business logic (no HTTP concerns)
│   │   ├── __init__.py
│   │   ├── agent_service.py      # Agent CRUD, prompt management
│   │   ├── agent_templates_service.py  # Runtime bridge to scripts/agent_templates
│   │   │                         #   (compose.py) — read-only, powers GET /agents/templates
│   │   │                         #   + POST /agents/from-template, the in-app template gallery
│   │   ├── call_service.py       # Call lifecycle, state machine
│   │   ├── test_call_service.py  # Places a call via the voice platform's hosted LLM (smoke test only — no configured model/tools, see phases/completed/phase0.md); also place_platform_agent_call/list_platform_agents, the dial-a-dashboard-built-agent path (ADR-012)
│   │   ├── voice_platform.py     # Abstract base for Retell/Vapi adapters
│   │   ├── retell_adapter.py     # Retell AI specific implementation
│   │   ├── vapi_adapter.py       # Vapi AI specific implementation
│   │   ├── tunnel_check.py       # PUBLIC_BASE_URL reachability probe, shared by the custom-LLM preflight guard and scripts/check_custom_llm.py
│   │   ├── public_url.py         # Resolves PUBLIC_BASE_URL; "auto" discovers the live quick-tunnel host from cloudflared (ADR-007)
│   │   ├── llm_service.py        # Provider-agnostic LLM calls (DeepSeek/OpenAI, ADR-008), tool execution
│   │   ├── sandbox_service.py    # Text-chat agent testing sandbox — no phone call, see "Agent testing sandbox" flow
│   │   ├── integration_service.py # *Calling* third parties: Cal.com book/cancel/reschedule/slots, HubSpot contact + credential verify
│   │   ├── integration_config_service.py # *Storing which* third parties a tenant connected — CRUD + validation for models/integration.py. Owns no HTTP; delegates verification to integration_service
│   │   ├── analytics_service.py  # Metrics computation, sentiment aggregation
│   │   ├── places_service.py     # Google Places search, city/country extraction, autocomplete — prospecting Agent 1, discovery (ADR-006)
│   │   ├── research_service.py   # Company research — prospecting Agent 2, knowledge base (ADR-006)
│   │   ├── script_service.py     # Call-script generation for prospects AND leads (build_prospect_prompt / build_lead_prompt)
│   │   ├── prospect_service.py   # Prospect CRUD, upsert-from-places, priority ranking, phone_match_key + call-outcome ladder (ADR-006)
│   │   └── lead_service.py       # Lead CRUD, retry/backoff state machine, dispatch, outcome evaluation (ADR-011)
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
│   │   ├── transfer_call.py      # NOT registered — handler raises; see tools/__init__.py
│   │   └── send_sms.py
│   │
│   ├── workers/                  # Celery tasks
│   │   ├── __init__.py
│   │   ├── celery_app.py         # Celery config + beat_schedule (dispatch_due_leads/sweep_stale_leads ADR-011, sweep_stale_prospects ADR-006)
│   │   ├── transcript_tasks.py   # Post-call transcript processing
│   │   ├── analytics_tasks.py    # Periodic metric rollups
│   │   ├── prospect_tasks.py     # discover_prospects / research_prospect / sweep_stale_prospects (ADR-006, 2026-08-21 correction)
│   │   └── lead_tasks.py         # dispatch_due_leads / sweep_stale_leads — the lead retry scheduler (ADR-011)
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
│   │   │   ├── layout.tsx        # Document + font only — no app chrome (see FRONTEND.md)
│   │   │   ├── page.tsx          # Public landing page at / — no sidebar, static
│   │   │   ├── (app)/            # Route group: everything behind the app chrome.
│   │   │   │   │                 #   Parens don't change URLs — /dashboard is still /dashboard
│   │   │   │   └── layout.tsx    #   Wraps children in AppShell
│   │   │   ├── dashboard/        # (under (app)/ — as are agents, calls, prospects, leads, settings)
│   │   │   │   └── page.tsx      # Main dashboard (setup checklist, Retell status, metrics, recent calls)
│   │   │   ├── agents/
│   │   │   │   ├── page.tsx      # Agent list — ?source=platform switches to the live Retell roster (ADR-012)
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
│   │   │   │   ├── page.tsx      # Prospecting pipeline UI (ADR-006) — grouped, URL-param filtered
│   │   │   │   └── [id]/
│   │   │   │       └── sandbox/
│   │   │   │           └── page.tsx  # Text-chat sandbox for one prospect's script — no phone call
│   │   │   ├── leads/
│   │   │   │   └── page.tsx      # Bark/warm-lead list + add form + per-lead scheduler controls (ADR-011)
│   │   │   ├── settings/
│   │   │   │   └── page.tsx      # Integrations, phone numbers, billing
│   │   │   └── api/strategist/
│   │   │       └── route.ts      # Next.js route proxying an LLM call for the agent-builder wizard — see FRONTEND.md
│   │   ├── components/           # components/ui + components/features split — see FRONTEND.md
│   │   │   ├── ui/                # Generic primitives, one per file, zero domain knowledge
│   │   │   │   ├── Button.tsx, Card.tsx, Badge.tsx, PageHeader.tsx, EmptyState.tsx, Skeleton.tsx, ...
│   │   │   │   └── index.ts      # re-export barrel, so imports stay `@/components/ui`
│   │   │   ├── layout/            # App chrome: AppShell, Sidebar, Topbar
│   │   │   ├── features/
│   │   │   │   ├── agents/       # AgentCard, AgentBuilder, Stepper, PromptEditor,
│   │   │   │   │                 #   PlatformAgentList (Retell-dashboard agents + inline dial, ADR-012),
│   │   │   │                 #   DynamicVariableFields ({{placeholder}} inputs, ADR-012a),
│   │   │   │                 #   TemplateGallery (industry/service/style picker over
│   │   │   │                 #   scripts/agent_templates — /agents/new's "Use a template" tab)
│   │   │   │   ├── calls/        # CallTable, TranscriptViewer, LiveCallPanel,
│   │   │   │   │                 #   CallEventTimeline (the CallEvent trail on /calls/[id] —
│   │   │   │   │                 #   flags a tool dispatched with no recorded result)
│   │   │   │   ├── settings/     # IntegrationCard (real /api/integrations CRUD + test),
│   │   │   │   │                 #   PhoneNumberTable (live platform number roster)
│   │   │   │   └── prospects/    # ProspectSearchForm, CityAutocomplete, ProspectFilters,
│   │   │   │                     #   ProspectSectionTabs (URL param `section`, client-side
│   │   │   │                     #   filter on Prospect.status), ProspectStatsStrip,
│   │   │   │                     #   ProspectGroupTree, ProspectRow (+ call-history line),
│   │   │   │                     #   ProspectDetailPanel, ProspectCallDrawer (fixed right-side
│   │   │   │                     #   panel — the call form; NOT rendered inside the tree, see
│   │   │   │                     #   its docstring), CsvImportButton, SyncCallsButton,
│   │   │   │                     #   SandboxChat, SandboxContextPanel, prospectStatus.ts
│   │   │   │   ├── leads/        # LeadCreateForm, LeadRow, LeadDetailPanel, LeadStatsStrip,
│   │   │   │   │                 #   leadStatus.ts (retry_state/status meta, ADR-011)
│   │   │   │   ├── dashboard/    # SetupChecklist (first-run steps, derived from live data),
│   │   │   │   │                 #   RetellStatus, SyncNotice (the de-jargoned stuck-call row)
│   │   │   │   └── marketing/    # Landing-page sections: MarketingNav, Hero, HowItWorks,
│   │   │   │                     #   FeatureGrid, Pricing, MarketingFooter
│   │   │   └── icons.tsx
│   │   ├── hooks/                 # all data fetching lives here (FRONTEND.md)
│   │   │   ├── useWebSocket.ts
│   │   │   ├── useCallMetrics.ts
│   │   │   ├── useCallEvents.ts   # one call's CallEvent trail; empty is normal, not an error
│   │   │   ├── useIntegrations.ts # /api/integrations CRUD + test, plus INTEGRATION_PROVIDERS
│   │   │   │                      #   (hand-synced with the backend's SUPPORTED/ALLOWED_CONFIG_KEYS)
│   │   │   ├── usePhoneNumbers.ts # live platform number roster
│   │   │   ├── useAgents.ts
│   │   │   ├── useLlmModels.ts
│   │   │   ├── usePlatformAgents.ts  # live Retell roster + per-agent {{variables}} + callPlatformAgent (ADR-012)
│   │   │   ├── useAgentTemplates.ts  # scripts/agent_templates gallery: list + createAgentFromTemplate
│   │   │   ├── useProspects.ts    # list + stats + research-status polling
│   │   │   ├── useCityAutocomplete.ts
│   │   │   ├── useProspectSandbox.ts
│   │   │   └── useLeads.ts        # list + stats + in_flight polling (ADR-011)
│   │   └── lib/
│   │       ├── api.ts            # Axios wrapper + auth-token interceptor
│   │       ├── types.ts          # Shared TS interfaces, hand-mirrored from backend/schemas/*.py — no codegen, see FRONTEND.md
│   │       ├── format.ts
│   │       ├── builder.ts
│   │       ├── constants.ts
│   │       ├── cx.ts             # className joiner, exported (was trapped, unexported, in the old ui.tsx)
│   │       ├── workspace.ts      # The ONE place the signed-in workspace/user is mocked until
│   │       │                     #   real auth lands — see FRONTEND.md
│   │       ├── dynamicVariables.ts  # prospect -> {{placeholder}} suggestion map (ADR-012a)
│   │       └── prospectGrouping.ts  # pure country -> category -> city -> companies grouping
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
    ├── test_prospects.py         # /api/prospects router: validation, tenant scoping, CSV import, per-prospect + batch calling, CSV export, sandbox-chat, city-autocomplete
    ├── test_prospect_service.py
    ├── test_prospect_tasks.py    # discover_prospects task: arguments reach places_service, source_location/city/country persist; sweep_stale_prospects re-enqueue logic
    ├── test_places_service.py    # addressComponents extraction, autocomplete normalization
    ├── test_research_service.py
    ├── test_script_service.py
    ├── test_leads.py              # /api/leads router: create-paused, lifecycle, tenant scoping, call-now (ADR-011)
    ├── test_lead_service.py       # backoff math, business-hours snapping, dispatch, outcome evaluation, idempotency
    ├── test_lead_tasks.py         # dispatch_due_leads / sweep_stale_leads task bodies
    ├── test_integrations.py       # /api/integrations router: validation, tenant scoping, merge-not-replace PUT, secret masking
    ├── test_nda_model.py          # NdaDispatch: the unique(lead_id, call_id) guarantee, states, tenant NDA fields
    └── test_tools/
        ├── test_book_appointment.py
        └── test_lookup_customer.py
```

This tree is a snapshot — it will drift again. When a change adds a new service, router,
worker, or top-level component, update this tree in the same change (see
[EFFICIENCY.md](EFFICIENCY.md)).

## Architecture decisions

Full write-ups — rationale, the real calls that drove each fix, what was rejected —
live in [ADR.md](ADR.md). Read the entry there when your change touches that decision;
this index is enough to know which one that is.

- **[ADR-001](ADR.md#adr-001-multi-tenancy-via-row-level-isolation)** — Multi-tenancy via row-level isolation
- **[ADR-002](ADR.md#adr-002-voice-platform-adapter-pattern)** — Voice platform adapter pattern
- **[ADR-003](ADR.md#adr-003-llm-tool-execution-is-server-side)** — LLM tool execution is server-side
- **[ADR-004](ADR.md#adr-004-websocket-for-live-call-monitoring)** — WebSocket for live call monitoring
- **[ADR-005](ADR.md#adr-005-celery-for-post-call-processing)** — Celery for post-call processing
- **[ADR-007](ADR.md#adr-007-webhooks-are-the-fast-path-reconciliation-is-the-source-of-truth)** — Webhooks are the fast path, reconciliation is the source of truth
- **[ADR-008](ADR.md#adr-008-provider-agnostic-llm-chosen-per-agent)** — Provider-agnostic LLM, chosen per agent
- **[ADR-009](ADR.md#adr-009-streaming-custom-llm-responses-with-barge-in-cancellation)** — Streaming custom-LLM responses with barge-in cancellation
- **[ADR-010](ADR.md#adr-010-the-agent-speaks-first-via-a-begin-message-on-call_details)** — The agent speaks first, via a begin message on `call_details`
- **[ADR-006](ADR.md#adr-006-prospecting-pipeline-prospector-researcher-agents)** — Prospecting pipeline (Prospector + Researcher agents)
- **[ADR-011](ADR.md#adr-011-lead-retry-scheduler-bark-com-and-other-warm-leads)** — Lead retry scheduler (Bark.com and other warm leads)
- **[ADR-012](ADR.md#adr-012-dialing-a-platform-native-agent-one-we-didnt-build)** — Dialing a platform-native agent (one we didn't build)

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
| **Change the lead retry scheduler** (backoff timing, business hours, success criteria) | `lead_service.py` (`compute_next_attempt`/`within_business_hours`/`evaluate_call_outcome`) → `config.py` if a threshold moves → `tests/test_lead_service.py` → `CONTEXT.md` ADR-011 if the policy itself changes, not just a number |
| **Add an integration provider or config key** | `integration_config_service.py`'s `SUPPORTED` / `ALLOWED_CONFIG_KEYS` (one line each — no migration; `config` is JSONB) → a `verify_*_credentials` function in `integration_service.py` and a branch in `integration_config_service.verify` → `schemas/integration.py`'s `SECRET_CONFIG_KEYS` if it brings a new secret name → `tests/test_integrations.py`. Do **not** add credentials to `ToolConfig` — see `models/integration.py` for why |
| **Add an outbound industry vertical** | one entry in `scripts/agent_templates/industries.py` (`qualifying_flow` / `vocabulary` / `extra_objection_rows` / `validated: False`) → add it to the `INDUSTRIES` dict → `uv run python scripts/build_agent_matrix.py --industry <key>`. Nothing else changes: `compose.py` picks it up for every existing style and service automatically, **including the in-app template gallery** (`agent_templates_service.list_templates()` reads `INDUSTRIES` directly, no separate registration). Keep `validated: False` until it has real-call data behind it — `compose.py` renders the unvalidated banner off that flag, and the gallery shows an "Unvalidated" badge off the same one. As of 2026-08-21, `INDUSTRIES` holds only `hvac_solar` (the validated leaf) and `roofing` — `dentist`/`car_rentals` were dropped as redundant cold-call verticals nobody was using; re-add by restoring their dict entries from git history if needed |
| **Add a one-off diagnostic agent** (not a sales leaf) | its own `scripts/seed_<name>_agent.py` with the prompt inline, mirroring `seed_email_transcription_test_agent.py` — deliberately *outside* the `agent_templates` matrix, since an agent with no hook/qualifying/close would otherwise bend every style and service module around it. `use_custom_llm=True` so it runs the same `retell_ws.py` path as real agents |
| **Stop a live call / change how hangups work** | `retell_adapter.py` (`stop_call`/`list_live_calls`) → `call_service.end_call` → `api/calls.py` and `scripts/kill_calls.py` (both call the service; keep the CLI dependency-free so it works when the API is down) → `tests/test_retell_adapter.py`. Terminal state stays `apply_retell_call_state`'s job — don't write status here (ADR-007) |
| **Change how platform-native agents are listed or dialed** (ADR-012) | `<platform>_adapter.py`'s `list_platform_agents` (normalization lives there, not in the service) → `test_call_service.list_platform_agents` / `place_platform_agent_call` → `schemas/agent.py`'s `PlatformAgent*` → `api/agents.py` (keep the routes ABOVE `/{agent_id}`) → `tests/test_retell_adapter.py` + `tests/test_test_call_service.py` → `frontend/src/hooks/usePlatformAgents.ts`. If the change touches `{{placeholders}}`, `_DYNAMIC_VARIABLE_RE` and the missing-value guard in `place_platform_agent_call` move together — a name the UI can't see is a name that gets spoken aloud. Do **not** add provisioning to this path — "we don't own this agent's config" is the whole distinction it encodes |
| **Offer the platform-agent source on another dial surface** | the surface's request schema (exactly-one-of validator, mirroring `ProspectCallRequest`) → its router, branching to `place_platform_agent_call` *before* any personalization work → the UI picker, and **say in the UI what the platform agent won't receive** — silently dropping a personalized prompt is the failure mode this pattern exists to prevent → its router test, asserting the personalized path was NOT taken |
| **Add work that must happen when a call ends** (lead or prospect) | `call_service._fanout_post_call` — branch on `Call.lead_id` / `Call.prospect_id`; keep it to a few local queries or enqueue to Celery (ADR-005), and give it its own idempotency guard, since the hook fires on `call_ended`, `call_analyzed` *and* a later reconcile |
| **Change how a prospect call's outcome maps to `Prospect.status`** | `prospect_service.outcome_status_for_call` (the pure per-call verdict) → `_OUTCOME_STATUS_ORDER` if the ladder changes → both consumers get it for free: `classify_call_outcome` (single call, forward-only) and `resync_status_from_calls` (whole history, may move status *down*) → `call_service.apply_retell_call_state` if it needs a new `Call` field off Retell's payload → `tests/test_prospect_service.py` |
| **Reconcile the platform's call history into the prospect ledger** | `retell_adapter.list_call_history` (paginated `/v2/list-calls`) → `call_service.backfill_from_platform` (match by `prospect_service.phone_match_key`, then `resync_prospects_from_calls`) → `POST /api/prospects/sync-calls` (above `/{prospect_id}`) → frontend `SyncCallsButton` → `tests/test_call_service.py`. This is the *only* path that sees a call this backend never placed (ADR-012 dashboard runs) |
| **Add a batch/bulk outbound action or a prospect CSV export** | `prospect_service` (`batch_call_targets` / `export_csv` — pure query + serialize) → `api/prospects.py`, declared *above* `/{prospect_id}` so the literal path wins → `schemas/prospect.py` → `tests/test_prospects.py` |
| **Dedupe or match phone numbers** | `prospect_service.phone_match_key` (last 10 digits — bridges E.164 vs national trunk-prefix). Use it for dedupe/matching; `normalize_phone` is validation/storage only. Backfill of pre-existing dupes: `scripts/merge_duplicate_prospects.py` |

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
4. Calls go out one at a time (`POST /api/prospects/{id}/call`) or in bulk
   (`POST /api/prospects/batch-call` — up to 50 not-yet-called prospects, highest
   priority first). Each `Call` row carries `prospect_id`.
5. When a call ends, `_fanout_post_call` → `prospect_service.classify_call_outcome`
   advances `Prospect.status` (`no_answer` / `called` / `flagged`) off how it ended.
   `GET /api/prospects/export` dumps the (optionally filtered) list as CSV, phone
   column first so it re-uploads into a Retell batch call.

### Inbound call
1. Caller dials → Twilio routes to Retell/Vapi
2. Voice platform does STT → sends text via webhook to `POST /webhooks/retell`
3. Webhook handler creates/updates `Call` record, publishes to Redis PubSub
4. `llm_service.call_claude()` with system prompt + conversation history + available tools
5. DeepSeek responds with text OR a tool call → we execute tool → return result to DeepSeek
6. Final text response sent back to voice platform → TTS → caller hears it
7. Loop continues until hangup or escalation trigger

### Outbound call (custom-LLM websocket)
1. `test_call_service` provisions/reuses a Retell agent pointing at
   `/llm-websocket/{call_id}` and dials the target
2. Retell opens the websocket → `retell_ws.py` resolves the `Call`/`Agent` by
   `external_id`, sends the `config` frame
3. Retell sends `call_details` → **the agent speaks first**: a begin message on
   `response_id: 0`, generated from the agent's own prompt (ADR-010). Skipped when the
   frame describes a reconnect rather than a fresh call
4. Each caller utterance → `response_required` → streamed turn, server-side tools, ledger
   checks (ADR-009/ADR-003); `reminder_required` covers caller silence
5. Every completed turn is persisted/broadcast via `_persist_and_publish_turn`

### Outbound call (platform-native agent, ADR-012)
1. Operator opens `/agents?source=platform` → `GET /api/agents/platform` proxies Retell's
   live agent roster (no local rows, nothing cached)
2. Operator picks one, enters a number → `POST /api/agents/platform/call`
3. `place_platform_agent_call` re-checks the id against the roster, then dials —
   **no provisioning, no prompt push, no tunnel, no websocket**
4. A `Call` row is written with `external_agent_id` and a null `agent_id`
5. Retell's own agent runs the conversation. Lifecycle events reach us only if the
   operator set our `/webhooks/retell` URL on that agent in Retell's dashboard;
   otherwise `POST /api/calls/sync` settles the row (ADR-007)

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

### Lead retry scheduler (ADR-011)
1. Operator types in a lead (Bark.com or otherwise) via `POST /api/leads` — lands
   `retry_state="paused"`.
2. Operator assigns an agent, writes notes, then `POST /{id}/start` arms it:
   `retry_state="scheduled"`, `next_attempt_at` set to the next business-hours slot.
3. Celery Beat's `dispatch_due_leads` (every 5 min) claims due leads still in the
   window, builds a personalized prompt (`script_service.build_lead_prompt`), and
   places the call through the same `test_call_service.place_test_call` path Prospects
   use, tagged with `lead_id`. `retry_state="in_flight"`, `attempt_count` +1.
4. The call proceeds exactly like any other outbound call (see "Outbound call" above)
   — nothing lead-specific happens mid-call.
5. On the call's `call_ended`/`call_analyzed` webhook (or a reconcile),
   `call_service`'s terminal-state hook calls `lead_service.evaluate_call_outcome`:
   answered-and-talked → `retry_state="succeeded"`; otherwise the backoff ladder picks
   the next `next_attempt_at`, or `retry_state="exhausted"` past the attempt cap.
6. `sweep_stale_leads` (same cadence) reconciles any lead stuck `in_flight` past
   `lead_stale_in_flight_minutes`, covering a lost webhook the same way ADR-007 already
   does for ordinary calls.

### Guardrails on what the agent says and who it says it to
Two guards sit between the model and the caller in `retell_ws.py`, both added after call
274a1b16 — a real prospecting call that demonstrated each failure once.

**Stage directions never reach the caller** (`_strip_meta_preamble`, `_PreambleGuard`).
The agent read its own script notes aloud: *"This is the first turn — Beat 1 of the
opener. One or two short sentences…"* before delivering the actual line. `_SPEECH_BLOCK`
already forbade this; the model did it anyway, which is the lesson — a prompt instruction
is a strong suggestion, not a guarantee, so anything that must never happen needs a check
in code. Leading sentences matching the outbound templates' own beat vocabulary
(`scripts/agent_templates/shared.py`) are dropped before the words go out.

Streaming makes this harder than it sounds: audio handed to Retell is already on its way
to the ear, so `_PreambleGuard` buffers the opening. It is two-stage so the latency cost
lands only where it's earned — a short probe is checked for markers, and a clean opening
(almost always) is released immediately and streams normally thereafter. If every
sentence looks like a direction the text is spoken **unchanged**: dead air on a
just-answered call is worse than one odd line.

**Phone menus end the call** (`_looks_like_ivr`, `IVR_AUTO_HANGUP_ENABLED`). Outbound
dialing hits switchboards constantly; the agent used to pitch into "press one for
accounts" and pay for the airtime. A menu on the line now ends the call with
`end_call: true` before any LLM call is spent on the turn. Detection requires two
independent markers because a false positive hangs up on a real person, and the flag
exists so it can be switched off without a deploy. The `CallEvent(event_type="ivr_hangup")`
row is written **before** the hangup frame — the opposite of every other write here,
because `end_call` makes Retell drop the socket immediately and a write started after it
loses that race.

### Agent testing sandbox
Try an agent's persona/system_prompt over text before spending a real call on it —
`frontend/src/app/agents/[id]/sandbox/page.tsx` → `POST /api/agents/{id}/sandbox-chat` →
`sandbox_service.chat()` → `llm_service.get_agent_response()`. Stateless: the client
resends the whole message history each turn, the same shape a live call already uses —
no new table, no session store. It takes a `system_prompt_override` directly as an
argument rather than off a Call row (there is no call), so the sandbox can run with an
unsaved prompt draft — that's the point of the feature. Tools default off (`tools_enabled=False`): `book_appointment`/`create_lead`
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
