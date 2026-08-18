# Phase 5 — CRM push + post-call NDA dispatch (Leads)

> **Status: Sessions 1 and 3 written, neither verified against anything real.** Sessions
> 2 and 4–6 not started. This file moves to `completed/` only once every session is done
> **and** real-call verified — passing tests is explicitly not the bar here (see
> `outliers.md` for the list of things unit tests missed).
>
> What "written but unverified" means concretely for S1/S3, as of 2026-08-17:
> `uv run ruff check` clean, `uv run pytest` 470 passed, `uv run mypy backend` unchanged
> (10 pre-existing errors, none in the new files). **The two migrations have NOT been
> applied to any database** — they're written and chained onto `a1c9e4f728b6`, nothing
> more. The shared Neon instance means applying one lands on teammates immediately (see
> RUN.md / CLAUDE.md), so that's a deliberate hand-off point, not an oversight. And no
> HubSpot credential has been through `POST /api/integrations/crm/test` against the real
> API yet — the verifier's request shape is unit-tested with a mock, which proves the
> plumbing and proves nothing about HubSpot.

Source: design discussion 2026-08-17. Scope is the **Leads** category (ADR-011) only:
after a lead call concludes, (1) push the contact + call outcome into a CRM, and (2) get
an NDA in front of the lead when they agreed to receive one.

Run the sessions in order. Sessions 1–2 (CRM) and 3–6 (NDA) are independent of each
other below the shared trigger in Session 1 — CRM can ship without NDA.

---

## Decisions taken up front

These were settled in the planning discussion. Recorded here so they aren't re-litigated
mid-implementation.

| Decision | Choice | Why |
|---|---|---|
| CRM push or pull | **Push only** — after each lead call | Leads arrive from Bark and are hand-entered (ADR-011). A CRM-as-lead-source importer is a separate feature with its own dedupe problem. |
| Which CRM first | **HubSpot**, behind a thin `CrmAdapter` | Free tier means we can probe the real API before coding (the repo's standing habit — see ADR-009 §4c). `create_hubspot_contact` already proves the credential path. HubSpot has a first-class *Calls* engagement object built for exactly this. GHL has no free tier and a churning v2 API. |
| What gets logged | **Every terminal lead call** as a call engagement; contact upsert + deal stage move **only on success** | "No answer, attempt 3" in the CRM is genuinely useful to the operator. Advancing a pipeline stage on a voicemail is not. |
| NDA delivery | **Dropbox Sign** (e-signature) | Free unlimited test mode with real webhooks, so the contract can be verified empirically first. Clean template + custom-fields API and a signed-doc download endpoint. **And it sends the email itself** — which removes the entire need for our own email infrastructure (no Resend/SES, no sending domain, no SPF/DKIM, no cold-domain deliverability risk on a legal document). |
| Who supplies the NDA template | **We do** — one platform-owned template | Therefore the Dropbox Sign credential is a *platform* credential in `config.py`, **not** a per-tenant `Integration` row. What is per-tenant is the NDA party data used as merge fields. |
| NDA send gate | **Post-call extraction proposes, operator confirms**, with a per-tenant auto-send toggle to enable later | See "The rejected mid-call gate" below. |

### The rejected mid-call gate — read this before "improving" the design

The obvious design is a mid-call `send_nda` tool the agent invokes once the lead agrees.
**It is not buildable today**, and the prerequisite that would make it buildable was
explicitly rejected as out of scope.

`test_call_service._provision_custom_llm_agent` rejects `system_prompt_override`
(`test_call_service.py:186-188`). Lead calls always pass a personalized prompt from
`script_service.build_lead_prompt`, so **every lead call is forced onto Retell's hosted-LLM
path**. On that path `backend/api/retell_ws.py` never runs, and `retell_ws.py` is the only
executor of `backend/tools/` — so no server-side tool can fire during a lead call at all
(ADR-003/ADR-008: the tool layer "only takes effect on the `use_custom_llm` path; Retell's
hosted LLM ignores it").

The fix would be a nullable `Call.system_prompt_snapshot` written at dispatch and preferred
by `retell_ws.py` over `Agent.system_prompt` — small, and it would fix the identical
limitation for Prospects. **It was rejected for this phase** because it touches the
live-call path, the highest-risk code in the repo. Do not quietly reintroduce it as part of
a session below.

Two consequences worth knowing:
- The gate is the *only* part of the design this changes. `NdaDispatch` and its state
  machine, the send worker, the signature webhook, the signed-doc path, the CRM push, and
  the UI are all identical regardless of what triggers them.
- It also *removes* work: with no mid-call tool there is no ADR-009 ledger entry to add, no
  `asyncio.shield` concern, and no in-turn latency budget to defend.

Both the mid-call tool and Retell's own hosted-LLM function calling (declaring a function
on the Retell agent that hits an endpoint of ours) remain clean **upgrades** to this
pipeline later. Neither is foreclosed.

---

## Session 1 — Tenant-scoped integration credentials + the post-call fanout [WRITTEN 2026-08-17, migration not applied]

**What landed:** `models/integration.py`, `schemas/integration.py` (with secret masking),
`services/integration_config_service.py`, `api/integrations.py` (registered in `main.py`),
migration `e2f7a4b91c68`, `integration_service.verify_hubspot_credentials`, and the
`_maybe_advance_lead` → `_fanout_lead_post_call` rename in `call_service.py`.
`tests/test_integrations.py` plus a cross-tenant credential-read case in `test_auth.py`.

Two things worth knowing that the plan below didn't anticipate:
- **PUT merges `config` rather than replacing it.** A UI that renders the masked secret
  back into its own form field would otherwise save the literal mask over the real key on
  the next save. An explicit empty string is how you clear a key.
- **Changing a credential clears `last_verified_at`.** Without that, a freshly pasted
  wrong key inherits the previous key's green tick.

**Why:** Two blockers before any of this can run. There is nowhere to put a tenant's CRM
key (`ToolConfig` is agent-scoped, has no `tenant_id`, has no CRUD route, and ADR-003's
flattening leaks every row's config into one shared `caller_context` — wrong shape for a
tenant-level concern). And `call_service._maybe_advance_lead` currently does exactly one
thing; both features need to hang off that same terminal-state hook.

Files: `models/integration.py` (new) → alembic revision → `schemas/integration.py` (new)
→ `api/integrations.py` (new, register in `main.py`) → `services/call_service.py` →
`CONTEXT.md` structure tree.

```
Add a tenant-scoped Integration model (models/integration.py): provider (str),
kind (str: "crm"), config (JSON), enabled (bool), with TenantMixin/UUIDMixin/
TimestampMixin and a unique constraint on (tenant_id, kind) — one CRM per tenant for
now. Deliberately NOT a ToolConfig row: that model is agent-scoped, carries no
tenant_id, and ADR-003's caller_context flattening shares every row's config across
all tools. Add the alembic revision, a schemas/integration.py, and an
api/integrations.py exposing GET/PUT /api/integrations (tenant_id via
Depends(get_current_tenant), never a query param) plus POST /api/integrations/test
that verifies the stored credential against the provider. Register the router in
main.py and add it to CONTEXT.md's structure tree.

Then, in call_service.py, rename/extend the _maybe_advance_lead hook into a
_fanout_lead_post_call(db, call) that still calls lead_service.evaluate_call_outcome
exactly as it does now, and additionally enqueues follow-up work. Keep all three
existing callers (handle_call_ended, handle_call_analyzed, reconcile_call) going
through the one function — that single-writer property is what ADR-007 established and
what gives the lead scheduler its self-healing. Enqueue only; never do the work inline
(ADR-005). No new task bodies in this session, just the fanout point.
```

Known gap to document, not solve: integration credentials are plaintext at rest, same as
`ToolConfig` today. Encryption-at-rest is a follow-up, not this phase.

---

## Session 2 — CRM push via a CrmAdapter

**Why:** `transcript_tasks._process` step 4 is a `pass` with a comment, but CONTEXT.md's
post-call flow already claims "if CRM integration configured, lead/contact created/updated
in HubSpot/Salesforce". The doc is ahead of the code. This closes that.

Files: `services/crm/base.py`, `crm/hubspot_adapter.py`, `crm/__init__.py`,
`services/crm_service.py`, `workers/crm_tasks.py` (all new) → `models/call.py` (one
column) → alembic revision → `tests/test_crm_service.py`, `tests/test_crm_tasks.py` →
`CONTEXT.md` (structure tree + new ADR).

```
Build the CRM push for lead calls.

1. services/crm/base.py: a CrmAdapter ABC mirroring VoicePlatformAdapter's shape
   (ADR-002), with exactly four methods — upsert_contact, log_call, set_stage,
   attach_document. Keep it thin; do NOT build a generic field-mapping engine.
2. services/crm/hubspot_adapter.py: the HubSpot implementation. Move/reuse the
   existing integration_service.create_hubspot_contact logic. log_call should create a
   HubSpot Calls engagement (the object type built for logging a phone call — duration,
   recording URL, body) associated to the contact.
3. services/crm/__init__.py: get_crm_adapter(provider) dispatching on a dict, same
   pattern as voice_platform.get_adapter().
4. services/crm_service.py: builds the payload from a Lead + Call + Transcript and
   resolves the tenant's Integration row. No provider-specific HTTP knowledge here.
5. workers/crm_tasks.py: sync_lead_call_to_crm(call_id), enqueued from
   _fanout_lead_post_call. Log EVERY terminal lead call as a call engagement; upsert
   the contact and move the deal stage ONLY when lead_service judged the call a
   success.
6. Idempotency: contact upsert-by-email is naturally idempotent, but call logging is
   not. Add a nullable crm_engagement_id column to Call, key the engagement on
   call.external_id, and skip if already logged. Two webhooks plus a reconcile all
   reach terminal status for the same call — this task must be safe to run repeatedly.

Verify against a real HubSpot free-tier account before considering it done — an actual
contact, an actual logged call, an actual stage move. Not just mocked tests.
```

Note the free property: because the trigger lives on ADR-007's single-writer terminal-state
path, a lost webhook that only gets picked up by reconciliation *also* enqueues this sync.
No second self-healing mechanism needed, same as ADR-011 got.

---

## Session 3 — NdaDispatch model + tenant NDA party data [WRITTEN 2026-08-17, migration not applied]

**What landed:** `models/nda.py` (`NdaDispatch`, `NDA_STATES`, `NDA_TERMINAL_STATES`), the
five NDA columns on `Tenant`, `schemas/nda.py`, migration `f3b8c5d02a17`, and
`tests/test_nda_model.py` — whose central test asserts the *database* rejects a second
dispatch for the same (lead, call), not that application code declines to write one.

`nda_auto_send` got `server_default=false` in the migration, not just a model default:
the safe default has to be true of tenant rows that predate the column, not only of new
ones.

**Why:** The whole NDA feature needs one persistent record with a real uniqueness
guarantee before any sending code exists. ADR-009's duplicate-call ledger is
connection-scoped — it dies with the websocket and cannot stop a retried Celery task or a
second webhook from sending a second copy of a legal document. That has to be a DB
constraint, and the same row doubles as the operator's audit trail and resend surface.

Files: `models/nda.py` (new) → `models/tenant.py` (merge-field columns) → alembic revision
→ `schemas/nda.py` (new) → `tests/` → `CONTEXT.md`.

```
Add models/nda.py with an NdaDispatch model (TenantMixin/UUIDMixin/TimestampMixin):
lead_id FK, call_id FK, recipient_email, recipient_name, provider,
provider_request_id (nullable), state, attempt_count, last_error (nullable),
signed_document_url (nullable), extraction_confidence (nullable), and
requested_at/sent_at/signed_at timestamps.

state is: pending_review | queued | sending | sent | viewed | signed | declined |
failed | blocked. "blocked" means we have no usable email; "pending_review" means
extraction proposed something and a human hasn't confirmed it.

Put a UNIQUE constraint on (lead_id, call_id). This is the persistent idempotency the
connection-scoped ledger in retell_ws.py cannot provide — one NDA per lead per call. An
operator resend is an explicit action that bumps attempt_count on the existing row, NOT
a second row.

Do NOT denormalize a nda_state column onto Lead — read it through the relationship.
Two sources of truth for one fact is exactly the mistake ADR-006's "two overlapping
outreach axes" note documents.

Separately, add the tenant-level NDA party data needed as merge fields on the platform
template: legal company name, signer name, signer title, signer email. These belong on
Tenant (or a tenant-settings row), not on Integration — we supply the template and send
from our own Dropbox Sign account, so there is no per-tenant e-sign credential.
```

---

## Session 4 — Post-call intent extraction

**Why:** This is the gate. The conversation has ended and we need two facts out of it: did
the lead affirmatively agree to receive an NDA, and what email address should it go to.

**Prefer `Lead.email` when Bark already supplied it** and fall back to transcript
extraction only when it's missing — when the email is already on the row, the extractor
only has to judge *consent*, which it is far more reliable at than transcribing a spoken
address. Reading an email address out of STT output is the top failure mode of this whole
feature.

Files: `services/nda_service.py` (new) → `workers/nda_tasks.py` (new) →
`services/call_service.py` (fanout enqueue) → `tests/test_nda_service.py`.

```
Add services/nda_service.py with an extraction step and workers/nda_tasks.py with an
extract_nda_intent(call_id) task, enqueued from _fanout_lead_post_call for lead calls
that reached a terminal status.

The extractor runs one llm_service call over the transcript with a strict output schema:
{agreed: bool, email: str|null, confidence: float, quote: str}. Require an explicit
affirmative — "let me think about it" or "send me some info" is not consent to a legal
document.

Email resolution order: Lead.email if present and valid, else the extracted address,
else nothing. Validate syntactically before accepting.

Outcome:
- agreed + usable email -> create the NdaDispatch in state "pending_review" with the
  email and the supporting quote pre-filled.
- agreed + no usable email -> state "blocked", so the operator can see it and fix it
  rather than it failing silently.
- not agreed -> create no row at all.

Then honor a per-tenant auto_send_nda flag: when it is on, a pending_review row with
confidence above a configured threshold advances straight to "queued". Default the flag
OFF. The point is to watch the extractor be right across real calls before trusting it
with an unsupervised legal send.
```

---

## Session 5 — The send worker + signature webhook

**Why:** Actually sending, and then tracking what happened to it.

Files: `services/integration_service.py` (Dropbox Sign functions) →
`workers/nda_tasks.py` → `api/webhooks.py` → `config.py` → `tests/`.

```
1. In integration_service.py, add send_signature_request / get_signature_request /
   download_signed_document for Dropbox Sign, following the conventions already in that
   file: _require for missing credentials with an actionable message,
   _raise_for_status_with_body so the provider's own error text survives, and a
   TimeoutException branch raising IntegrationTimeoutError. Pin whatever API version
   header Dropbox Sign uses, with a comment, the way CAL_API_VERSION is pinned.
2. workers/nda_tasks.py: send_nda_dispatch(dispatch_id), guarded on state == "queued"
   so it is safe to run twice. Resolve the platform template id and credential from
   config.py, merge the tenant party fields plus the lead's name/company/date, send,
   then move the row to "sent" with provider_request_id.
3. On IntegrationTimeoutError, move the row to "sending" and DO NOT retry — a blind
   retry is a second NDA in someone's inbox. Add a reconcile task that queries the
   provider for a request matching this dispatch's metadata and settles the state from
   the provider's answer. Same philosophy as ADR-007: the provider is authoritative and
   pollable, not just push-based.
4. api/webhooks.py: POST /webhooks/dropbox-sign, signature-verified against the raw
   request bytes (read the body directly, do not take a parsed Pydantic model — same
   reason the Retell handler doesn't), tenant-unscoped like the other webhook routes,
   resolving the row by provider_request_id and advancing state on
   signature_request_sent/_viewed/_signed/_declined. Return in under 200ms; enqueue any
   real work (ADR-005).
5. On _signed: download the executed document, store it to S3, and push it to the CRM
   via CrmAdapter.attach_document.

VERIFY THE WEBHOOK CONTRACT EMPIRICALLY BEFORE CODING IT. Dropbox Sign requires the
response body to echo a specific literal string or it treats delivery as failed, and it
posts the payload as multipart form data rather than a JSON body. Confirm both against
their test mode first — this is the same class of detail as Retell's nested call object
and Cal.com's rotating uid, both of which cost real calls to discover.
```

---

## Session 6 — Prompt beat + operator UI

**Why:** The extractor can only read what the conversation actually contains. The agent has
to ask for consent and have the lead confirm their email back. And a `pending_review` row
is useless without somewhere to review it.

Files: `services/script_service.py` → `scripts/agent_templates/` →
`api/leads.py` → `hooks/useLeads.ts` → `components/features/leads/` →
`lib/types.ts` → `FRONTEND.md`.

```
1. script_service.build_lead_prompt gains an [NDA] block adding a closing beat: ask
   whether we can send the NDA, and if yes get the email address spelled out and read
   back for confirmation. Follow the existing spoken-email conventions already in
   retell_ws.py's guidance (speak addresses as words, never symbols; confirm before
   using).
2. Include that block ONLY when the tenant has the NDA feature configured. The model
   must never offer to send something the backend cannot deliver — that is the
   send_sms lesson (phase4.md Session 1) and it applies here verbatim.
3. api/leads.py: GET /api/leads/{id}/nda, POST /api/leads/{id}/nda/approve (the
   pending_review -> queued transition, with an editable email so the operator can fix
   a mistranscription), and POST /api/leads/{id}/nda/resend.
4. Frontend, per FRONTEND.md conventions: fetching in hooks/useLeads.ts,
   components/features/leads/ndaStatus.ts mirroring the existing leadStatus.ts for
   state metadata and labels, an NDA badge column on the leads list, and the
   review/approve/resend controls plus the signed-document link in LeadDetailPanel.
   Hand-sync lib/types.ts.
5. Add an Integrations card to the settings page for the CRM connection and the
   per-tenant auto_send_nda toggle.
```

---

## Two ADRs to write when this lands

- **CRM push via `CrmAdapter` + tenant-scoped `Integration`** — why a new tenant-level
  table rather than more `ToolConfig` rows, why HubSpot first, why the adapter stayed at
  four methods, and why the trigger sits on the existing single-writer terminal-state path
  rather than adding a second one.
- **NDA dispatch: post-call extraction, human confirmation, persistent idempotency** —
  including why the mid-call tool was rejected (the hosted-LLM tool gap above), why the
  uniqueness guarantee had to be a DB constraint rather than the ADR-009 ledger, and why a
  timeout is settled by reconciliation rather than retry.

## Open items deliberately left out of this phase

- `Call.system_prompt_snapshot` and the custom-LLM path for lead calls — rejected above.
  Everything here works without it.
- Encryption at rest for integration credentials.
- GoHighLevel / Salesforce adapters. The interface exists so they're new files; nobody has
  asked yet.
- CRM as a *lead source* (pull). Separate feature, separate dedupe problem.
- Counsel review of the platform NDA template, and a per-tenant record of accepting it.
  Not an engineering task, but cheap now and awkward to retrofit — we would be sending a
  legal document from our own account on a tenant's behalf.
