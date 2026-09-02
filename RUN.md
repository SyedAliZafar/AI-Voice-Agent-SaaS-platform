# Running the app

## Before you start

Copy `.env.example` to `.env` and fill in the real values. Three that matter most:

- `DATABASE_URL` — the **shared** Neon Postgres (get it from a teammate; it is not
  committed). Change `postgresql://` to `postgresql+asyncpg://` and `?sslmode=require`
  to `?ssl=require`, or asyncpg rejects it.
- `CF_TUNNEL_TOKEN` + `PUBLIC_BASE_URL` — the named Cloudflare tunnel, so Retell can
  reach your machine.
- The provider keys: `RETELL_API_KEY`, `DEEPSEEK_API_KEY` / `OPENAI_API_KEY`.

No migration step — the schema is already applied on the shared database.

## Step 1

```bash
docker compose --profile tunnel up -d
```

Starts everything the backend needs: redis, minio, the API on `:8000`, the Celery worker
and beat scheduler, and the Cloudflare tunnel that gives Retell a public URL.

## Step 2

```bash
uv sync --extra dev
```

Installs the Python dependencies on your host, for the scripts in the steps below.

## Step 3

```bash
uv run python scripts/dev_token.py
```

Seeds the demo tenant and prints a 30-day bearer token — every `/api/*` route needs one.

## Step 4

```bash
echo "NEXT_PUBLIC_DEV_AUTH_TOKEN=<token from step 3>" > frontend/.env.local
```

Hands the dashboard that token so its API calls are authenticated.

## Step 5

```bash
cd frontend
npm install
npm run dev
```

Runs the Next.js dashboard on `:3000`.

## Step 6

Open http://localhost:3000/dashboard — API docs are at http://localhost:8000/docs.

## Stopping

```bash
docker compose --profile tunnel down
```

Stop the tunnel when you are done — it publishes your local backend to the internet.

## Checks

```bash
uv run pytest
uv run ruff check .
uv run mypy backend
```


docker compose up --build