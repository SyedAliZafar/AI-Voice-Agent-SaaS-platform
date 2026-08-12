# CLAUDE.md

Read [CONTEXT.md](CONTEXT.md) first — it has the architecture, ADRs, data flows, prompt
structure, the "Change recipes" table (what files a given kind of change touches), and
the "what not to build" list. This file only covers commands and rules for working in
this repo day-to-day. See [EFFICIENCY.md](EFFICIENCY.md) for how to work efficiently in
this specific repo, and [FRONTEND.md](FRONTEND.md) for the target frontend/UI structure.

## Commands

### Backend (Python 3.12+, uv)
```
uv sync --extra dev              # install deps
uv run uvicorn backend.main:app --reload   # run API locally
uv run pytest                    # run tests
uv run ruff check .              # lint
uv run ruff format .             # format
uv run mypy backend              # type check
uv run alembic -c backend/migrations/alembic.ini upgrade head      # apply migrations
uv run alembic -c backend/migrations/alembic.ini revision --autogenerate -m "..."  # new migration
# Run both from the repo root: alembic.ini resolves script_location, and config.py finds
# .env, relative to the CWD. They also hit the SHARED Neon database — a migration you
# apply lands on your teammates immediately. See RUN.md.
uv run celery -A backend.workers.celery_app worker --loglevel=info  # run worker
```

### Frontend (Next.js, in `frontend/`)
```
npm install
npm run dev
npm run build
npm run lint
```

### Full stack
```
docker-compose up        # postgres, redis, minio, api, worker
```

## Hard rules
- Every DB query must go through tenant scoping: the `get_current_tenant` FastAPI
  dependency (`backend/api/deps.py`) resolves `tenant_id` from the bearer token on every
  `/api/*` route, and `backend/models/base.py`'s `TenantMixin` carries the column. Never
  bypass the `tenant_id` filter. (There used to be a `backend/middleware/tenant.py` —
  it was written, never registered, and deleted in favor of `deps.py`, since
  `BaseHTTPMiddleware` can't raise per-route 401s, can't participate in DI for tests to
  override, and is skipped for WebSocket scopes. See `phases/completed/phase0.md` Task 2 for the full
  reasoning.) `/webhooks/*` routes are the deliberate exception — voice platforms can't
  send our JWT, so they stay unscoped by tenant middleware and rely on the payload's own
  ids instead.
- Voice platform logic goes through the `VoicePlatformAdapter` interface
  (`backend/services/voice_platform.py`), never call Retell/Vapi SDKs directly from routes.
- Tool execution stays server-side (`backend/tools/`) per ADR-003 — don't move it into
  the voice platform config.
- Webhook handlers must return in <200ms: enqueue to Celery, don't do work inline
  (see ADR-005).
- Run `uv run ruff check .` and `uv run pytest` before considering backend work done.
- Never commit `.env` — only `.env.example` with placeholder values.

## Docs
- After a batch of structural work (new file/module, a flow changes, a change-recipe
  row goes stale, an ADR-worthy decision), sync CONTEXT.md/FRONTEND.md in a dedicated
  `docs: sync ...` commit before moving to the next unrelated task — see `16ccfb9` for
  the pattern. Don't update docs for bug fixes or internal refactors that don't change
  file roles or flow.
