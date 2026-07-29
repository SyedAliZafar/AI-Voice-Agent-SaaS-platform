# Running the app

Two ways to run this locally: full Docker Compose stack, or manual (backend/frontend
in your own terminals). Pick one.

## Option A — Docker Compose (everything, including the worker)

```bash
cp .env.example .env   # fill in real API keys
docker compose up --build
```

Starts postgres, redis, minio, the API (`:8000`), and the Celery worker together.
Then in a separate terminal for the frontend:

```bash
cd frontend
npm install
npm run dev
```

Dashboard: http://localhost:3000/dashboard · API docs: http://localhost:8000/docs

You'll need an auth token before either is useful — see "Getting an auth token" below.

## Option B — Manual (run pieces yourself)

```bash
# infra only
docker compose up -d postgres redis minio

# deps + migrations
uv sync --extra dev
cd backend/migrations && uv run alembic upgrade head && cd ../..

# API
uv run uvicorn backend.main:app --reload
```

Then, in a separate terminal, start the Celery worker:

```bash
uv run celery -A backend.workers.celery_app worker --loglevel=info
```

**Skip the worker terminal for solo dev:** set `CELERY_TASK_ALWAYS_EAGER=true` in `.env`
and restart the API — tasks then run inline in-process, no worker needed. Never set this
outside local dev; staging/prod need a real worker to keep webhook responses under
200ms (ADR-005 in `CONTEXT.md`).

Frontend, same as Option A:

```bash
cd frontend
npm install
npm run dev
```

## Getting an auth token

Every `/api/*` route requires a bearer token — the backend reads `tenant_id` from its
claims (`backend/api/deps.py`) rather than trusting a query parameter. There's no login
flow yet, so mint one for the demo tenant:

```bash
uv run python scripts/dev_token.py
```

That seeds the demo tenant row if missing and prints a 30-day token. Use it either way:

```bash
# curl / Swagger
curl -H "Authorization: Bearer <token>" http://localhost:8000/api/agents
```

For the dashboard, put it in `frontend/.env.local` as `NEXT_PUBLIC_DEV_AUTH_TOKEN=<token>`
and restart `npm run dev`. (A value in `localStorage.auth_token` overrides it, which is
handy for testing a second tenant — mint one with `--tenant-id <uuid>`.)

## Exposing the API publicly (Retell webhooks / custom-LLM websocket)

Retell can't reach `localhost`. To give it a public URL:

```bash
docker compose --profile tunnel up
```

The `tunnel` service logs a `https://<random>.trycloudflare.com` URL that forwards to the
API. It's opt-in on purpose — starting it publishes your local backend to the internet.
Only run it with auth working, and stop it when you're done.

Note: `/webhooks/*` are deliberately unauthenticated (voice platforms can't send our JWT)
and do **not** yet verify platform signatures — so while the tunnel is up, anyone with the
URL can post forged call events. That's fine for a short debugging session, not for
leaving running.

## Tests

```bash
uv run pytest
```

Uses an in-memory SQLite DB and mocks the LLM client + voice platform adapters — no
real API keys or running services needed.

## Everyday checks

```bash
uv run ruff check .
uv run ruff format .
uv run mypy backend
```
