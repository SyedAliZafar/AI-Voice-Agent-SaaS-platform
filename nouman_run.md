# Quick run — commands only

Full details/troubleshooting: [RUN.md](RUN.md). This is just the command list.

## 1. First time / after pulling changes

```bash
cp .env.example .env      # fill in real API keys + shared DATABASE_URL (ask a teammate)
uv sync --extra dev
cd frontend && npm install && cd ..
```

DB is shared Neon — no migrations needed on a fresh clone.

## 2. Start everything (Docker — API + worker + redis + minio)

```bash
docker compose up --build
```

Frontend (separate terminal):

```bash
cd frontend
npm run dev
```

## 3. Recreate the tunnel (Retell needs a public URL to reach you)

Quick tunnel (hostname changes every restart):

```bash
docker compose --profile tunnel-quick up
```

Set once in `.env` so a restart doesn't need a manual URL update:

```
PUBLIC_BASE_URL=auto
```

Named tunnel (permanent hostname, needs Cloudflare setup done once — see RUN.md):

```bash
docker compose --profile tunnel up -d
docker compose up -d api      # recreate — `restart` does NOT re-read .env
```

## 4. Recreate just the API after an `.env` change

```bash
docker compose up -d api
```

## 5. Celery worker + beat (needed for prospect research, lead retries — anything scheduled)

Manual mode (no Docker worker):

```bash
uv run celery -A backend.workers.celery_app worker --loglevel=info
uv run celery -A backend.workers.celery_app beat --loglevel=info
```

Skip both for solo dev — set in `.env` and restart the API instead:

```
CELERY_TASK_ALWAYS_EAGER=true
```

## 6. Auth token (needed for every API call / the dashboard)

```bash
uv run python scripts/dev_token.py
```

Put the printed token in `frontend/.env.local`:

```
NEXT_PUBLIC_DEV_AUTH_TOKEN=<token>
```

## 7. Migrations (only when you added a new one)

```bash
uv run alembic -c backend/migrations/alembic.ini upgrade head
```

## 8. Checks before calling something done

```bash
uv run ruff check .
uv run pytest
cd frontend && npm run build
```

## 9. Quick diagnostics

```bash
curl $PUBLIC_BASE_URL/health              # is the tunnel actually working
uv run python scripts/check_custom_llm.py # full chain: config -> tunnel -> LLM -> websocket
uv run python scripts/list_platform_agents.py  # what Retell actually has on the account
uv run python scripts/kill_calls.py       # list/kill live calls (needs only RETELL_API_KEY)
```
