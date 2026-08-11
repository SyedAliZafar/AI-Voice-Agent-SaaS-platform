# Running the app

Two ways to run this locally: full Docker Compose stack, or manual (backend/frontend
in your own terminals). Pick one.

## The database is shared — read this first

Everyone on the team points at **one Neon Postgres**, so a call placed or a prospect
searched on your machine is immediately visible on your teammate's. Nothing about the
data lives in git.

- Get the connection string from a teammate (it is not committed) and put it in your
  own `.env` as `DATABASE_URL`. Two edits to what Neon's dashboard shows you, both
  required: `postgresql+asyncpg://` instead of `postgresql://`, and `?ssl=require`
  instead of `?sslmode=require` (asyncpg rejects the latter).
- **A fresh clone does not need to run migrations** — the schema is already applied on
  the shared instance. Only run them when you add a new migration.
- `docker compose` no longer starts a local Postgres. It is behind a `local-db` profile
  precisely so it can't silently shadow the shared one and give you a private, diverging
  copy. If you deliberately want throwaway local data, see `.env.example`.
- Since you share a database, you also share its state: a destructive migration or a
  bulk delete hits your teammate too. Say so before you run one.

## Troubleshooting quick reference

| Symptom | What to do |
|---|---|
| Calls stuck at "In progress", 0s duration | Press **Sync status** on the Calls page (or `POST /api/calls/sync`) — see ["When calls are stuck"](#when-calls-are-stuck-showing-in-progress) |
| Custom-LLM test call returns a 422 "not reachable" | The tunnel is down — this is the preflight guard working as intended, not a bug. It just saved you a billed call to dead air. Check `docker compose logs tunnel`, or run `scripts/check_custom_llm.py` for the full chain. |
| Quick tunnel (`tunnel-quick`): `docker compose ps` shows `Up` but nothing works | Don't trust it — check `docker compose logs tunnel-quick` for the *current* `https://*.trycloudflare.com` URL, or `curl $PUBLIC_BASE_URL/health`. It sits in a silent reconnect loop while still reporting `Up`. Set `PUBLIC_BASE_URL=auto` (below) so the current URL is discovered automatically, or switch to the named tunnel (Option A) so this stops happening. |
| Quick tunnel restarted and `PUBLIC_BASE_URL` is stale again | Set `PUBLIC_BASE_URL=auto` in `.env` once. The hostname is then read live from cloudflared's `/quicktunnel` endpoint, and a test call that hits a stale URL re-resolves and retries by itself. No more copy-paste-from-logs. |
| Named tunnel (`tunnel`): `docker compose ps` shows unhealthy | Trustworthy this time — its healthcheck calls cloudflared's own `/ready`. Check `docker compose logs tunnel` for why the connection isn't registering (bad `CF_TUNNEL_TOKEN` is the usual cause). |
| Changed `PUBLIC_BASE_URL` in `.env` but nothing changed | `docker compose restart api` does **not** re-read `.env` — run `docker compose up -d api` to recreate the container. |
| Custom-LLM (DeepSeek) call gives dead air, nothing in the logs | `uv run python scripts/check_custom_llm.py` — walks config → tunnel → LLM → websocket and prints which link is broken |
| Webhooks returning 401 | Confirm `RETELL_API_KEY` is the key with the **webhook badge** in Retell's dashboard — only that one signs requests |
| Need to see what a caller actually said | `GET /api/calls/{id}/transcript` or the Calls page → call detail — see ["Transcripts"](#transcripts) below |

## Option A — Docker Compose (everything, including the worker)

```bash
cp .env.example .env   # fill in real API keys + the shared DATABASE_URL
docker compose up --build
```

Starts redis, minio, the API (`:8000`), and the Celery worker together — the database is
the shared Neon instance from your `.env`, not a container. Then in a separate terminal
for the frontend:

```bash
cd frontend
npm install
npm run dev
```

Dashboard: http://localhost:3000/dashboard · API docs: http://localhost:8000/docs

You'll need an auth token before either is useful — see "Getting an auth token" below.

## Option B — Manual (run pieces yourself)

```bash
# infra only (no postgres — the DB is the shared Neon instance in .env)
docker compose up -d redis minio

# deps
uv sync --extra dev

# API
uv run uvicorn backend.main:app --reload
```

No migration step: the shared database already has the schema. When you *do* add a
migration, run it from the repo root — `alembic.ini` sets `script_location` relative to
the current directory, and `config.py` reads `.env` relative to it too, so running from
inside `backend/migrations` finds neither:

```bash
uv run alembic -c backend/migrations/alembic.ini upgrade head
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

Retell can't reach `localhost`. Two ways to give it a public URL — pick one profile.
Both are opt-in by design: starting either publishes your local backend to the internet,
so only run one with auth working (`backend/api/deps.py`), and stop it when you're done.

### Option A — Named tunnel (recommended)

A permanent hostname: set `PUBLIC_BASE_URL` once and it never changes again, so no
re-provisioning churn and no risk of a stale URL silently going dead mid-session.
Needs a free Cloudflare account and a domain you control.

**One-time setup:**
```bash
cloudflared tunnel login                                    # opens a browser, pick a zone
cloudflared tunnel create voiceagent                        # prints a tunnel UUID
cloudflared tunnel route dns voiceagent voiceagent.<your-domain>
cloudflared tunnel token voiceagent                          # prints the token
```
Put that token in `.env` as `CF_TUNNEL_TOKEN`, and set
`PUBLIC_BASE_URL=https://voiceagent.<your-domain>`. Then:

```bash
docker compose --profile tunnel up -d
docker compose up -d api   # recreate — `restart` alone does not re-read .env
```

`docker compose ps` now reports a real health status for the `tunnel` service (backed by
cloudflared's own `/ready` endpoint, not just "the process is running") — see the
troubleshooting table below for what a failing healthcheck means.

### Option B — Quick tunnel (zero setup, not for anything you'll leave running)

```bash
docker compose --profile tunnel-quick up
```

Logs a `https://<random>.trycloudflare.com` URL that forwards to the API. No account
needed, but two things bite:
- The hostname changes on **every restart**. **Fix: set `PUBLIC_BASE_URL=auto` in `.env`
  once.** The backend then reads the live hostname from cloudflared's own metrics
  endpoint (`/quicktunnel`, exposed by the `--metrics` flag on the `tunnel-quick`
  service) at the moment it needs it, so a restart needs no `.env` edit and no container
  recreate. A custom-LLM test call that finds a stale URL re-resolves and retries once
  before failing, so even an in-flight restart is usually invisible. See
  `backend/services/public_url.py`. Without `auto`, you must update `PUBLIC_BASE_URL` and
  recreate the API container after every restart.
- The tunnel can **silently die mid-session** while `docker compose ps` still reports it
  as `Up` — it sits in a reconnect loop instead of exiting. This is what caused custom-LLM
  calls to go to dead air on 2026-08-04 (see `phases/completed/phase3.md`): the tunnel died ~45 minutes
  after being restarted, and nothing surfaced that until a live call failed.

If you hit that, don't trust `docker compose ps` — check `docker compose logs tunnel` for
the *current* URL, or `curl $PUBLIC_BASE_URL/health`.

### Either way

Two things need `PUBLIC_BASE_URL`: Retell's Custom LLM websocket, and the per-agent
`webhook_url` that call lifecycle events are delivered to. Without it, calls never leave
`in_progress` until you press "Sync status" on the Calls page (see below).

As of the tunnel-death incident above, placing a **custom-LLM** test call now preflights
`PUBLIC_BASE_URL` reachability before dialing (`backend/services/tunnel_check.py`) — an
unreachable tunnel fails immediately with a 422 explaining why, instead of silently
spending a real, billed call on dead air. This check is custom-LLM-only; the hosted-LLM
path is designed to work with no tunnel at all and must keep working without one.

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

## Transcripts

Every call gets a transcript, written two ways depending on the path:

- **Custom-LLM (DeepSeek) calls** write it live, turn-by-turn, as the conversation
  happens (`retell_ws.py` → `call_service.record_turns`).
- **Every call** — custom-LLM or Retell's hosted LLM — also gets Retell's own post-call
  `transcript_object` written as the authoritative final version once `call_ended` /
  `call_analyzed` arrives. This is the *only* writer for hosted-LLM calls, which have no
  live websocket.

View it on a call's detail page (`/calls/{id}`) or `GET /api/calls/{id}/transcript`. A
call that never resolves (stuck `in_progress`, see above) never gets the final write
either — reconciling it is what unblocks both the status and the transcript.

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
broken, without spending a phone call. Its tunnel-reachability step (step 2) shares code
with the preflight check `place_test_call` now runs automatically before every custom-LLM
dial (`backend/services/tunnel_check.py`), so the two can't drift apart.

The usual culprit is a stale `PUBLIC_BASE_URL` — most common on the quick tunnel (Option
B above), whose hostname changes every restart and which **can still report `Up` in
`docker compose ps` while actually dead**, sitting in a silent reconnect loop. Trust
`curl $PUBLIC_BASE_URL/health`, not the container status. The named tunnel (Option A)
doesn't have this problem — its healthcheck reflects real connection state.

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
