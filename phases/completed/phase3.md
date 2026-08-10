# Phase 3 — Call lifecycle correctness + reaching the DeepSeek path

**Status: complete and verified end-to-end on a live call (2026-08-02).** 114 tests pass,
ruff is clean, the frontend builds — and a real outbound call to +49176•••••••3 was
answered by **DeepSeek over the Custom LLM websocket**, then correctly resolved to
`status=resolved, duration=91s, sentiment=0.5` from real Retell webhooks.

This is the first time ADR-003's actual architecture has ever run a live call. phase0.md
noted the hosted-LLM test call deliberately bypasses DeepSeek; that gap is now closed.

This picks up from `phase0.md`, which closed the four de-risking gates and handed off to
the Custom LLM WebSocket migration. Two problems surfaced immediately on first real use.

## The two bugs

### 1. Every call was stuck at `in_progress`, 0m 0s, sentiment n/a

Not one bug — two independent causes, either one sufficient on its own.

**Cause A: the webhook payload shape was wrong.** `RetellWebhookEvent` required a
top-level `call_id`. Retell actually nests it:

```json
{"event": "call_ended", "call": {"call_id": "...", "duration_ms": 12345, ...}}
```

So every genuine Retell webhook failed validation with a 422 *before* reaching a handler.
`handle_call_ended` — the only thing that sets `status="resolved"` and `duration_sec` —
never ran once. Two follow-on errors came from the same misreading of Retell's contract:
the code branched on a `transcript_update` event that Retell does not send as a webhook at
all (it's a *websocket* message type from the custom-LLM protocol), and it ignored
`call_analyzed`, which is the event carrying `user_sentiment` — hence the permanent "n/a".

**Cause B: Retell was never told where to send webhooks.** `webhook_url` appeared nowhere
in the codebase. Retell supports per-agent webhooks and an account-level fallback; neither
was configured, so even a correctly-shaped handler had nothing arriving at it.

### 2. There was no way to use DeepSeek from the UI

`Agent.use_custom_llm` gates hosted-LLM vs. our Custom LLM websocket, and the backend for
it was already complete — model column, schemas, `_provision_custom_llm_agent`,
`backend/api/retell_ws.py`. But **no UI control existed**, so the only way to flip it was a
raw `PATCH /api/agents/{id}`. Worse, the Test call card hardcoded "Runs on Retell's
built-in LLM" regardless of the flag, so it would have lied once the flag was on.

## What was done

### Webhook correctness
- `schemas/webhook.py` — `RetellWebhookEvent` now models the nested `call` object, with
  `call_id`/`transcript` as accessors. The docstring records the old shape and why it
  broke, so it doesn't regress.
- `api/webhooks.py` — branches on the three real events. Reads the **raw** body (needed
  for signature verification), then validates. `call_analyzed` is handled for sentiment.
- `retell_adapter.parse_webhook` had the identical flat-payload bug. It was dead code (the
  route parses via Pydantic), but a second wrong parser lying around is a trap — fixed.

### Webhook delivery
- `create_agent_with_llm` / `create_agent_with_custom_llm` take and send `webhook_url`,
  built from `PUBLIC_BASE_URL` as `{base}/webhooks/retell`.
- **The subtle part:** a Retell agent's webhook URL is fixed at creation, and
  `_provision_hosted_llm_agent` only created an agent when none was cached. So the existing
  "Ali" agent would have kept its old, webhook-less Retell agent forever and the fix would
  have silently done nothing for it. The cache is now keyed on `webhook_url` too, and
  re-provisions on mismatch — mirroring what the custom-LLM path already did for `ws_url`.
- `webhook_url` stays optional: the hosted path is meant to work with no tunnel at all.
  The cost of that (no lifecycle events) is covered by reconciliation.

### Reconciliation (ADR-007)
Webhooks are best-effort. Tunnels go down, `PUBLIC_BASE_URL` gets forgotten, the
cloudflared host changes every restart — and a missed `call_ended` stranded a row forever.

- `RetellAdapter.get_call()` → `GET /v2/get-call/{id}`.
- `call_service.reconcile_call()` / `reconcile_stale_calls()` apply the platform's
  authoritative state.
- `POST /api/calls/sync` (tenant-scoped) + a "Sync status" button on the Calls page.
- Both the webhook and reconcile paths write through one function,
  `apply_retell_call_state()`. Deliberate: two writers could disagree about the same call.
- Richer status mapping via `disconnection_reason` — `call_transfer` → `escalated`,
  dial failures and `error*` → `failed`, otherwise `resolved`. This replaces the old
  `# no richer signal available yet` comment, which is no longer true.
- Duration prefers Retell's `duration_ms` over wall-clock arithmetic, because a reconcile
  may run days after the call ended.

### Signature verification
`/webhooks/*` were unauthenticated, which phase0.md flagged as becoming load-bearing the
moment a tunnel is opened — and the DeepSeek path *requires* an open tunnel.

- `RetellAdapter.verify_webhook_signature()` delegates to the official `retell-sdk`
  (new dependency). Deliberately not hand-rolled: the scheme is HMAC-SHA256 over
  `body + timestamp` with a 5-minute replay window, and a subtly wrong reimplementation
  would reject every webhook — presenting *exactly* like the bug above, but harder to spot.
- Gated by `RETELL_VERIFY_WEBHOOKS` (default true).
- **Note for anyone following Retell's docs:** they show `Retell.verify(...)` as a
  classmethod. That does not exist in the v5 SDK — it's `from retell.lib import verify`.

### DeepSeek path reachable
- `Agent.use_custom_llm` added to `frontend/src/lib/types.ts` (it was missing — the
  hand-sync drift ../../FRONTEND.md warns about).
- A "Conversation engine" card on the agent detail page switches between Retell's hosted
  LLM and DeepSeek, and the Test call copy now reflects which brain will actually answer,
  including the tunnel requirement.
- Fixed `[object Object]` in the Voice config card — `String(val)` on the nested
  `retell`/`retell_custom` provisioning objects.

### Contract tightening
`CallResponse.status` is now a `Literal[...]` instead of a bare `str`, matching what
`frontend/src/lib/types.ts` already assumed. ../../FRONTEND.md flagged this drift with the
frontend as the stricter side; the backend has been brought up to it.

## The third bug, found during verification: a dead tunnel is invisible

When the DeepSeek path was first switched on, it silently did nothing. The cause was not
in the code at all: `PUBLIC_BASE_URL` pointed at a cloudflared quick tunnel from a previous
session whose hostname no longer resolved. **The `tunnel` container still reported `Up`** —
it had been in a failed reconnect loop for two days, logging
`ERR Serve tunnel error ... Retrying connection` every ~15s while looking healthy to
`docker compose ps`.

So Retell was told to dial `wss://<dead-host>/llm-websocket`, DNS failed, and the caller
got dead air. Nothing appeared in our logs, because nothing ever reached us.

The reconcile path then confirmed this independently and retroactively — every stranded
call came back from Retell with `call_status=error`,
`disconnection_reason=error_llm_websocket_open`. That is Retell saying, in its own words,
"I could not open your websocket."

Two lessons worth keeping:
- `docker compose ps` showing `Up` for the tunnel proves nothing. Check
  `docker compose logs tunnel` for the *current* URL, or just curl
  `$PUBLIC_BASE_URL/health`.
- A quick tunnel's hostname changes on **every** restart, and `PUBLIC_BASE_URL` must be
  updated and the api container **recreated** (`docker compose up -d api`) each time.
  `scripts/check_custom_llm.py` now catches all of this in about five seconds.

## Diagnostic tooling

`uv run python scripts/check_custom_llm.py` walks the same chain Retell walks and reports
which link is broken, without spending a phone call:

1. Config — `PUBLIC_BASE_URL` / `DEEPSEEK_API_KEY` present
2. Tunnel — `GET {PUBLIC_BASE_URL}/health` actually resolves
3. DeepSeek — a real completion, proving key + model + `base_url`
4. WebSocket — connects to `wss://.../llm-websocket/{id}` **from the public internet**,
   seeding and cleaning up a temporary agent/call row, and runs a full
   `response_required` exchange against real DeepSeek

Run this *before* placing a test call whenever the custom-LLM path misbehaves. Each failure
prints the specific fix.

## Verified end-to-end (2026-08-02)

All of the following were observed on a real call, not asserted in tests:

| Check | Evidence |
|---|---|
| Retell reaches our websocket | `WebSocket /llm-websocket/call_b0841aa7d61… [accepted]` from `100.20.5.228` |
| DeepSeek answers the call | diagnostic step 4 returned `'PONG'` over `wss://` through the tunnel |
| Webhooks parse (the nested-payload fix) | 3× `POST /webhooks/retell → 200 OK` — not 422 |
| Signature verification works on real traffic | those same posts passed with `RETELL_VERIFY_WEBHOOKS=true` — not 401 |
| `call_ended` resolves the call | row moved to `resolved`, `duration_sec=91` |
| `call_analyzed` writes sentiment | `sentiment_score=0.5` (Retell `user_sentiment: Neutral`) |
| Re-provision-on-URL-change | agent's cached `webhook_url`/`ws_url` rewritten from the dead host to the live one automatically |
| Reconcile repairs stranded calls | `POST /api/calls/sync` → `updated: 9` |
| Status mapping is genuinely differentiated | `user_hangup` → `resolved`; `error_llm_websocket_open` → `failed` |

## How to re-verify from scratch

1. Start a tunnel: `docker compose --profile tunnel up -d`, take the printed
   `https://*.trycloudflare.com` URL, set `PUBLIC_BASE_URL` in `.env`.
2. **Recreate the API container** — `docker compose up -d api`. `restart` alone does not
   re-read `.env` (this has bitten before; see phase2.md).
3. Place a test call from the agent page and hang up. The row should move to `resolved`
   with a real duration and transcript. That is the proof the webhook now parses *and*
   gets delivered.
4. Hit "Sync status" on the Calls page — the 5 pre-existing stuck rows should resolve
   (they were placed by agents provisioned without a `webhook_url`, so no webhook will
   ever arrive for them; reconciliation is the only thing that can fix them).
5. Flip the agent to **DeepSeek (custom LLM)** and place another call. Watch for
   `/llm-websocket/{call_id}` in the API logs.
6. Confirm a forged unsigned POST to `/webhooks/retell` returns 401 while real Retell
   events still succeed. If *every* event starts failing, check that `RETELL_API_KEY` is
   the key with the webhook badge in Retell's dashboard — only that one signs.

Shortcut: `uv run python scripts/check_custom_llm.py` covers steps 1–2 and the whole
DeepSeek chain without a phone call. Only steps 3–5 need real telephony.

## What's still open

Carried over, unchanged by this phase:
- `transfer_call`, `send_sms`, `lookup_customer` return fabricated success.
  `transfer_call`'s own docstring calls it "the most important tool in the system," and
  the `escalated` status now written on `call_transfer` is meaningless until it's real.
- `CallEvent` still has zero write sites — no per-tool-call/transfer/error record, only
  the transcript (see "Since resolved" below — `Transcript.turns` itself is done).
- The Custom LLM websocket is **non-streaming**: one blocking `get_agent_response()` per
  turn. phase0.md measured 1.389s p95 non-streaming against a 1.5s budget, and noted a
  single tool call doubles the round-trips. This is the next thing that will hurt.
  [RESOLVED — ../in-progress/phase4.md Session 5 / ../../CONTEXT.md ADR-009]: streaming +
  barge-in cancellation shipped; `get_agent_response()` is now only the kill-switch-off
  fallback path.
- `system_prompt_override` (per-prospect personalization) is rejected on the custom-LLM
  path — the WS handler reads `Agent.system_prompt` fresh from the DB per call, so a
  call-time override has nowhere to live. (The text sandbox added below *does* support an
  override, since it's a plain request rather than a WS handler reading the DB.)
- Vapi's webhook still has no signature verification.
- No CI, no production deployment path. Clerk login unbuilt.
- `uv run mypy backend` reports ~11 pre-existing errors (openai types, missing jose/celery
  stubs, model forward refs) — untouched by this phase.

**Since resolved (LLM provider switching, live transcript, sandbox):**
- ~~`Transcript.turns` is still only ever `[]`~~ — `backend/api/retell_ws.py` writes it
  turn-by-turn as a live call happens (after each response is sent, off the latency path);
  `apply_retell_call_state` parses Retell's post-call `transcript_object` as the
  authoritative final write, which also covers the hosted-LLM path.
- ~~`ws.py`'s `publish_call_event` is called from nowhere~~ — called after each persisted
  turn; the dashboard's live call monitor has something to show now.
- ~~`llm_service.py` hardcoded to DeepSeek~~ — ADR-008: provider-agnostic, model chosen
  per-agent via `Agent.llm_model` and the "Conversation engine" card.
- ~~No sandbox to try a prompt/persona via text chat~~ —
  `/agents/{id}/sandbox` → `POST /api/agents/{id}/sandbox-chat`.

## Could be done next

Roughly in order of how much they'd hurt to skip:

1. **Prove the DeepSeek path on a live call** (step 5 above). Everything else here is
   scaffolding for that; it has still never run.
2. **Make the real tools real**, starting with `transfer_call`. A streaming tool-calling
   loop built over fabricated tools would be building on sand.
3. **Stream the WS responses.** phase0.md's measurement says streaming is what makes the
   architecture viable rather than a nice-to-have — first audio at ~0.7s regardless of
   total length. Reuse the warm client; don't construct `AsyncOpenAI` per call.
4. **Write `CallEvent` rows** for tool calls/transfers/errors during a call — turns are
   now persisted (see "Since resolved"), but individual events still aren't.
5. **Scheduled reconciliation** — `POST /api/calls/sync` is manual today. A periodic Celery
   task would close the loop without anyone clicking a button.
6. **CI** — ruff + pytest on every PR. There is none, and this phase's regression
   (a payload-shape mismatch caught only by a real call) is exactly what tests catch.
