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

Set `PUBLIC_BASE_URL` in `.env` to that URL and **recreate** the API container
(`docker compose up -d api` — `restart` alone does not re-read `.env`). Two things need
it: Retell's Custom LLM websocket, and the per-agent `webhook_url` that call lifecycle
events are delivered to. Without it, calls never leave `in_progress` until you press
"Sync status" on the Calls page (see below).

`/webhooks/retell` verifies Retell's `X-Retell-Signature` (`RETELL_VERIFY_WEBHOOKS=true`
by default), so a forged POST is rejected with 401. Retell only signs with the API key
carrying the **webhook badge** in their dashboard — if every event starts failing
verification, that's the first thing to check. `/webhooks/vapi` is still unverified.

## When calls are stuck showing "In progress"

Webhook delivery is best-effort — no tunnel, an unset `PUBLIC_BASE_URL`, or a tunnel that
restarted mid-call all mean the `call_ended` event is simply lost, and the row sits at
`in_progress` with 0s duration forever.

Press **Sync status** on the Calls page (or `POST /api/calls/sync`) to pull authoritative
state — status, duration, transcript, sentiment — straight from the voice platform for
every still-in-progress call. See ADR-007 in `CONTEXT.md`.

## Using a Custom LLM instead of Retell's built-in LLM

On an agent's detail page, the **Conversation engine** card switches between:

- **Retell built-in LLM** (default) — zero setup, no tunnel. Server-side tools are *not*
  exercised.
- **Custom LLM** — Retell relays the conversation to our websocket
  (`backend/api/retell_ws.py`), which answers with server-side tools plus whichever model
  you pick in the **Model** dropdown that appears once this is selected (DeepSeek or
  OpenAI, ADR-008 in `CONTEXT.md`). Requires `PUBLIC_BASE_URL` and a running tunnel, plus
  that model's API key (`DEEPSEEK_API_KEY` or `OPENAI_API_KEY`) — a model whose provider
  has no key set shows as disabled in the dropdown.

Switching re-provisions the agent with Retell on the next test call automatically.

**If the custom-LLM path "does nothing"** — the caller hears dead air and nothing appears
in the logs — run:

```bash
uv run python scripts/check_custom_llm.py
```

It walks the same chain Retell walks (config → tunnel → LLM → websocket, ending with a
real completion over `wss://` from the public internet) and tells you which link is
broken, without spending a phone call.

The usual culprit is a stale `PUBLIC_BASE_URL`. **A dead tunnel still reports `Up` in
`docker compose ps`** — it sits in a silent reconnect loop. Trust
`curl $PUBLIC_BASE_URL/health`, not the container status.

## Trying an agent without a phone call

Click **Try in sandbox** on an agent's detail page (`/agents/{id}/sandbox`) to chat with
its persona over text — no `RETELL_FROM_NUMBER`, no tunnel, no telephony spend. Edit the
system prompt in the pane on the right and it's used for your very next message, whether
or not you've clicked "Save prompt" yet; that button writes the draft back to the agent.
Server-side tools (`book_appointment`, `create_lead`, ...) are off by default — they hit
real integrations — flip "Run server-side tools" on to actually exercise the tool-calling
loop.

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
