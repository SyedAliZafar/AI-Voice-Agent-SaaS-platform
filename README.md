# Voice Agent SaaS Platform

Multi-tenant SaaS for building, deploying, and monitoring AI voice agents on
top of Retell AI and Vapi AI, with Claude as the conversation brain.

Read `CONTEXT.md` first — it has the full architecture, ADRs, and coding
conventions. This README is just setup steps.

## Quickstart

### 1. Backend

```bash
# Install dependencies
pip install -e ".[dev]" --break-system-packages
# or: uv pip install -e ".[dev]"

# Copy env template and fill in real API keys
cp .env.example .env

# Start postgres, redis, minio
docker compose up -d postgres redis minio

# Run migrations
cd backend/migrations && alembic upgrade head && cd ../..

# Start the API
uvicorn backend.main:app --reload

# In a separate terminal, start the Celery worker
celery -A backend.workers.celery_app worker --loglevel=info
```

Solo local dev: set `CELERY_TASK_ALWAYS_EAGER=true` in `.env` and skip the worker
terminal entirely — tasks then run inline in-process. Never set this outside local dev;
staging/prod need a real worker to keep webhook responses under 200ms (see ADR-005 in
`CONTEXT.md`).

API docs available at `http://localhost:8000/docs` (FastAPI auto-generates
OpenAPI docs from the routers).

### 2. Frontend

```bash
cd frontend
npm install
npm run dev
```

Dashboard available at `http://localhost:3000/dashboard`.

### 3. Full stack via Docker Compose

```bash
docker compose up --build
```

## Running tests

```bash
pytest
```

Tests use an in-memory SQLite DB and mock the Anthropic client + voice
platform adapters — no real API keys needed to run the suite.

## What to build next

Follow the phases in your project scope doc:
1. Wire up real Retell/Vapi API calls in `backend/services/retell_adapter.py`
   and `vapi_adapter.py` (currently stubbed with the right shape but no
   live credentials)
2. Implement `call_service.handle_call_started` to resolve `agent_id` from
   the dialed phone number (currently a placeholder)
3. Fill in `workers/transcript_tasks.py` to fetch full transcripts from the
   voice platform's API and run sentiment analysis
4. Add real auth (Clerk/Auth0) — `middleware/tenant.py` currently expects a
   JWT with `tenant_id` and `sub` claims
5. Build out the agent builder wizard UI beyond the name/platform form

See `CONTEXT.md` → "What NOT to build (for now)" before you reach for
custom STT/TTS or a billing engine.
# AI-Voice-Agent-SaaS-platform
