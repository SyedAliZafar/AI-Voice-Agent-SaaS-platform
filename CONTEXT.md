# CONTEXT.md — AI Voice Agent SaaS Platform

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
| LLM | DeepSeek API (OpenAI-compatible) | Conversation engine, intent detection, function calling |
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
│   │   └── base.py               # DeclarativeBase, TenantMixin
│   │
│   ├── schemas/                  # Pydantic request/response schemas
│   │   ├── __init__.py
│   │   ├── agent.py
│   │   ├── call.py
│   │   └── webhook.py
│   │
│   ├── api/                      # FastAPI routers
│   │   ├── __init__.py
│   │   ├── agents.py             # CRUD for agents + prompt config
│   │   ├── calls.py              # Call history, transcript retrieval
│   │   ├── analytics.py          # Metrics, aggregations
│   │   ├── webhooks.py           # POST /webhooks/retell, POST /webhooks/vapi
│   │   └── ws.py                 # WebSocket endpoint for live call streaming
│   │
│   ├── services/                 # Business logic (no HTTP concerns)
│   │   ├── __init__.py
│   │   ├── agent_service.py      # Agent CRUD, prompt management
│   │   ├── call_service.py       # Call lifecycle, state machine
│   │   ├── voice_platform.py     # Abstract base for Retell/Vapi adapters
│   │   ├── retell_adapter.py     # Retell AI specific implementation
│   │   ├── vapi_adapter.py       # Vapi AI specific implementation
│   │   ├── llm_service.py        # DeepSeek API calls, tool execution
│   │   ├── integration_service.py # CRM, calendar, custom webhook integrations
│   │   └── analytics_service.py  # Metrics computation, sentiment aggregation
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
│   │   └── analytics_tasks.py   # Periodic metric rollups
│   │
│   ├── middleware/
│   │   ├── tenant.py             # Extract tenant from JWT, set context
│   │   ├── rate_limit.py         # Redis-based rate limiting
│   │   └── logging.py            # Structured JSON logging
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
│   │   │   │   │   └── page.tsx  # Agent detail + prompt editor
│   │   │   │   └── new/
│   │   │   │       └── page.tsx  # Create agent wizard
│   │   │   ├── calls/
│   │   │   │   ├── page.tsx      # Call history with filters
│   │   │   │   ├── [id]/
│   │   │   │   │   └── page.tsx  # Single call detail + transcript
│   │   │   │   └── live/
│   │   │   │       └── page.tsx  # WebSocket live call monitor
│   │   │   └── settings/
│   │   │       └── page.tsx      # Integrations, phone numbers, billing
│   │   ├── components/
│   │   │   ├── CallTable.tsx
│   │   │   ├── MetricCard.tsx
│   │   │   ├── AgentCard.tsx
│   │   │   ├── TranscriptViewer.tsx
│   │   │   ├── PromptEditor.tsx  # Monaco-based prompt editing
│   │   │   └── LiveCallPanel.tsx # Real-time call audio + transcript
│   │   ├── hooks/
│   │   │   ├── useWebSocket.ts
│   │   │   └── useCallMetrics.ts
│   │   └── lib/
│   │       ├── api.ts            # Axios/fetch wrapper
│   │       └── types.ts          # Shared TypeScript interfaces
│   └── tailwind.config.ts
│
└── tests/
    ├── conftest.py               # Fixtures: test DB, test client, mock voice platform
    ├── test_agents.py
    ├── test_calls.py
    ├── test_webhooks.py
    ├── test_llm_service.py
    └── test_tools/
        ├── test_book_appointment.py
        └── test_lookup_customer.py
```

## Architecture decisions

### ADR-001: Multi-tenancy via row-level isolation
Every model has a `tenant_id` FK. A middleware extracts tenant from JWT on every
request and injects it into the DB session as a default filter. No schema-per-tenant —
too much operational overhead at this stage. Revisit if we hit 500+ tenants with
data isolation requirements.

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

## Key data flows

### Inbound call
1. Caller dials → Twilio routes to Retell/Vapi
2. Voice platform does STT → sends text via webhook to `POST /webhooks/retell`
3. Webhook handler creates/updates `Call` record, publishes to Redis PubSub
4. `llm_service.call_claude()` with system prompt + conversation history + available tools
5. DeepSeek responds with text OR a tool call → we execute tool → return result to DeepSeek
6. Final text response sent back to voice platform → TTS → caller hears it
7. Loop continues until hangup or escalation trigger

### Post-call processing (Celery)
1. Call ends → voice platform sends `call_ended` webhook
2. Handler enqueues: `process_transcript`, `compute_sentiment`, `sync_to_crm`
3. Transcript stored in DB + S3 (audio), sentiment score written to `calls` table
4. If CRM integration configured, lead/contact created/updated in HubSpot/Salesforce

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
