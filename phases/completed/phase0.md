# Phase 0 — De-risking before the Custom LLM WebSocket migration

**Status: complete.** All four tasks below are done — the WS migration can now start.

The goal is to move conversation intelligence out of Retell's hosted LLM and into this
backend over a Retell Custom LLM WebSocket, leaving Retell as telephony transport only.
That direction matches ADR-003. Phase 0 exists because an audit found the migration would
otherwise have been built on three unverified foundations:

1. **No public ingress** — Retell physically could not reach this backend. No tunnel, no
   proxy, no deployment path.
2. **No auth** — `tenant_id` was an unauthenticated query parameter, six endpoints had no
   tenant check at all, and `tenant_middleware` was written but never registered. Opening
   ingress would have exposed cross-tenant read/write plus a `test-call` endpoint able to
   dial arbitrary numbers on our Retell/Twilio account.
3. **Unproven telephony** — no phone had ever actually rung (see `phase2.md`).

Plus one unknown that could have invalidated the whole architecture: DeepSeek's latency.

## Status

| Task | Status |
|---|---|
| 1. Prove the phone rings | **Done** |
| 2. Real auth | Done |
| 3. Dev ingress | Done (opt-in) |
| 4. Latency spike | Done — **GO** |

### Task 1 — telephony (done)

Bought a number in the Retell dashboard (`+14059146006`), set `RETELL_FROM_NUMBER` in
`.env`, recreated the API container (`docker compose up -d api` — note `restart` alone
does not re-read `.env`), then placed a real call via `POST /api/agents/{id}/test-call`.
**The phone rang and the agent spoke its `system_prompt`.** The Twilio SIP-trunk path was
deliberately not used — see `phase2.md`, which also documents the credential bug that was
fixed along the way (the code now works, but this path needed none of it).

Worth restating explicitly, since it's easy to mistake for a bug: this call did **not**
exercise DeepSeek or any server-side tool. Retell's own hosted LLM answered — that's by
design for this endpoint (see `backend/services/test_call_service.py`'s docstring and the
"Test call" UI copy). It proves the telephony leg — Twilio number → Retell → a phone
ringing with audio — works end-to-end. It does not prove anything about our conversation
brain, because the hosted-LLM path is built specifically to bypass it. Closing that gap
(DeepSeek + real tools actually running a live call) is the entire point of the WS
migration this phase was de-risking.

### Task 2 — auth

`backend/api/deps.py` provides `get_current_tenant`, a FastAPI dependency that decodes the
bearer token and returns its `tenant_id` claim, raising 401 on anything else. Chosen over
middleware deliberately: `BaseHTTPMiddleware` can't raise per-route 401s, can't participate
in DI (so tests can't override it), and is skipped for WebSocket scopes — which matters for
the socket work coming next. `backend/middleware/tenant.py` was deleted as superseded.

Every `/api/*` route now takes `tenant_id` from that dependency instead of a query param,
and the previously unscoped lookups (`get_agent`, `update_agent`, `delete_agent`,
`test_call`, `get_call`, `get_transcript`, plus all of `prospects.py`) are tenant-filtered
at the service layer, returning 404 rather than 403 so ids stay non-enumerable.

In `prospect_service`, the tenant-blind lookup still needed by Celery tasks is now named
`get_prospect_unscoped()` — the safe name is the default, the unsafe one is explicit.

Not covered, by necessity: `/webhooks/*`. Retell and Vapi cannot send our JWT. **These
still have no signature verification** — the follow-up is noted in `backend/api/webhooks.py`
and becomes load-bearing the moment a tunnel is left running.

Dev tokens: `uv run python scripts/dev_token.py` seeds the demo tenant and mints one. The
frontend reads `NEXT_PUBLIC_DEV_AUTH_TOKEN` (or `localStorage.auth_token`). Real login via
Clerk remains unbuilt — `CLERK_SECRET_KEY` is still unread.

Coverage went from 43 tests to 93, including `tests/test_auth.py`, which asserts every
protected route rejects both a missing and a forged token, and that one tenant's token
cannot read, delete, or place a call against another tenant's agent.

### Task 3 — dev ingress

`docker compose --profile tunnel up` starts a cloudflared quick tunnel fronting the API.
Opt-in on purpose: starting it publishes the local backend to the internet. `uvicorn` now
runs with `--proxy-headers --forwarded-allow-ips=*` so it builds correct https/wss URLs
behind it. Documented in `../../RUN.md`.

### Task 4 — latency (GO)

`uv run python scripts/measure_llm_latency.py`. Measured against `deepseek-chat`, n=20,
after 2 discarded warmup runs:

| | p50 | p95 |
|---|---|---|
| Time to first token (streaming) | 0.688s | 0.951s |
| Total completion (today's non-streaming behaviour) | 1.105s | 1.389s |

Budget is 1.5s (`../../CONTEXT.md`). Both pass — **but read the second row carefully.**
Non-streaming total sits at 1.389s p95 with ~0.1s of headroom, and a single tool call
doubles the LLM round-trips. Non-streaming will blow the budget the moment tools are in
play; streaming holds first-audio at ~0.7s regardless of total length. So the model choice
is fine, and streaming is specifically what makes the architecture viable rather than a
nice-to-have.

Separate finding: the *first* request on a cold client costs ~2.5s (DNS + TLS). A
long-lived call server holds a warm client so this doesn't hit real calls — but don't
construct a fresh `AsyncOpenAI` per call in the WS handler, or every call starts with two
seconds of dead air.

## What this unblocks, and what's still missing

All four gates are now closed. The WS migration can start. Build the socket endpoint
*alongside* the hosted-LLM path behind a per-agent flag so there is always a working
fallback, prove one call end-to-end, then layer in memory → real tools → streaming →
observability.

Known gaps, updated as of the Custom LLM WebSocket MVP (`backend/api/retell_ws.py`) going
live and being verified against a real call:

**Since resolved, past sessions built these:**
- ~~No webhook signature verification~~ — `backend/api/webhooks.py` now verifies
  `X-Retell-Signature` (`settings.retell_verify_webhooks`, on by default).
- ~~Calls could strand at `in_progress` forever if a webhook never arrived~~ —
  `call_service.reconcile_call`/`reconcile_stale_calls`, exposed as `POST /api/calls/sync`,
  pulls authoritative state from Retell's `GET /v2/get-call` and self-heals.
- Webhook and reconcile paths now converge on one writer, `apply_retell_call_state`, so
  they can't disagree about the same call's outcome.
- The frontend has a real toggle for `use_custom_llm` (`frontend/src/app/agents/[id]/page.tsx`)
  — this isn't curl-only anymore.
- ~~`llm_service.py` hardcoded to DeepSeek~~ — ADR-008 (../../CONTEXT.md): provider-agnostic
  (`provider_for`/`get_client`, one cached `AsyncOpenAI` per provider), model chosen
  per-agent (`Agent.llm_model`) via the "Conversation engine" card, `GET /api/agents/models`
  reports the catalog and which providers are configured.
- ~~No per-turn conversation persistence; `Transcript.turns` always `[]`~~ —
  `backend/api/retell_ws.py` now writes turns after each response is sent
  (`call_service.record_turns`), and `apply_retell_call_state` parses Retell's post-call
  `transcript_object` as the authoritative final write (covers the hosted-LLM path too,
  which has no WS handler). `CallEvent` still has zero write sites — tool-invocation
  events specifically are still not recorded, see below.
- ~~`ws.py`'s `publish_call_event` called from nowhere~~ — the WS handler now calls it
  after persisting each turn, so the dashboard's live call monitor has something to show.
- ~~No sandbox to try a prompt/persona via text chat~~ —
  `frontend/src/app/agents/[id]/sandbox/page.tsx` → `POST /api/agents/{id}/sandbox-chat` →
  `sandbox_service.chat()`. Stateless, tools off by default.

**Still open:**
- `transfer_call`, `send_sms`, `lookup_customer` return fabricated success. `transfer_call`'s
  own docstring calls it "the most important tool in the system." Make them real before
  building a streaming tool-calling loop over them.
- `CallEvent` still has zero write sites — no record of individual tool invocations,
  transfers, or errors during a call, only the transcript.
- No CI, no production deployment path.
- The Custom LLM websocket is still non-streaming — one blocking LLM call per turn.
  phase0.md's own latency spike (below) says this is what will hurt once tools are in play.
