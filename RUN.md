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
