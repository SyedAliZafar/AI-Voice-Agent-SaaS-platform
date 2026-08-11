# Voice Agent SaaS Platform

Multi-tenant SaaS for building, deploying, and monitoring AI voice agents on
top of Retell AI and Vapi AI. DeepSeek/OpenAI power the conversation brain,
chosen per agent (ADR-008 in `CONTEXT.md`).

Read `CONTEXT.md` first — it has the full architecture, ADRs, data flows, and
coding conventions. This file is just the fastest path to a running stack.
For day-to-day run/troubleshooting detail (public tunnel setup, stuck calls,
custom-LLM debugging, ...), see `RUN.md`.

## Quickstart

### 1. Environment

```bash
cp .env.example .env   # fill in real API keys: Retell, Google Places, DeepSeek/OpenAI, ...
```

`DATABASE_URL` is the one value you can't invent: the team shares a single Neon Postgres
so everybody sees the same calls, prospects and leads. Ask a teammate for the string —
it isn't in git — and see `RUN.md` for the two edits it needs (`postgresql+asyncpg://`
and `?ssl=require`).

### 2. Full stack (Redis, MinIO, API, worker)

```bash
docker compose up --build
```

No Postgres container: the database is the shared remote one from your `.env`. (A local
one still exists behind `--profile local-db` for throwaway data — it's opt-in so it can't
silently shadow the shared DB and hand you a private, diverging copy.)

Solo local dev: set `CELERY_TASK_ALWAYS_EAGER=true` in `.env` so tasks run inline
in-process — no separate worker needed. Never set this outside local dev; staging/prod
need a real worker to keep webhook responses under 200ms (ADR-005 in `CONTEXT.md`).

**Migrations do not run on container start** — nothing in the image or compose command
invokes Alembic. A fresh clone needs no migration step anyway, since the schema is
already applied on the shared database. After *adding* a migration, apply it yourself
from the repo root (`alembic.ini` resolves `script_location`, and `config.py` finds
`.env`, relative to the current directory — running from inside `backend/migrations`
finds neither):

```bash
uv sync --extra dev
uv run alembic -c backend/migrations/alembic.ini upgrade head
```

API docs at `http://localhost:8000/docs` (FastAPI auto-generates OpenAPI docs from the
routers).

### 3. Auth token

There's no login flow yet — mint a 30-day bearer token for the demo tenant:

```bash
uv run python scripts/dev_token.py
```

Use it with curl (`Authorization: Bearer <token>`), or put it in
`frontend/.env.local` as `NEXT_PUBLIC_DEV_AUTH_TOKEN` so the dashboard picks it up
automatically. See RUN.md → "Getting an auth token" for the full flow.

### 4. Frontend

```bash
cd frontend
npm install
npm run dev
```

Dashboard at `http://localhost:3000/dashboard`.

### 5. (Optional) Public tunnel

Only needed if Retell must reach your backend — the Custom LLM path, or webhook
delivery for call lifecycle events. Not needed just to browse the dashboard or run
prospect discovery/research.

```bash
docker compose --profile tunnel-quick up -d --force-recreate tunnel-quick
```

Then set `PUBLIC_BASE_URL=auto` in `.env` (once) and run `docker compose up -d api`
to pick it up (`restart` alone doesn't re-read `.env`). Opt-in by design — starting
this publishes your local backend to the internet, so only run it once auth is
working, and don't leave it running unattended. See RUN.md → "Exposing the API
publicly" for the named-tunnel alternative, recommended for anything you'd leave
running (permanent hostname, no restart churn).

## Running tests

```bash
uv run pytest
```

Uses an in-memory SQLite DB and mocks the LLM client + voice platform adapters — no
real API keys or running services needed.

## What NOT to build

See `CONTEXT.md` → "What NOT to build (for now)" before reaching for custom
STT/TTS, real-time browser audio streaming, or a billing engine.
