"""Per-tenant integration settings: which third parties a tenant has connected.

**Not to be confused with `integration_service.py`**, which is the opposite half of the
same story and the reason this file's name is as long as it is:

  integration_service.py         — *calling* third parties (Cal.com, HubSpot HTTP)
  integration_config_service.py  — *storing which* third parties a tenant connected

This file owns no HTTP. When it needs to check a credential it delegates to
`integration_service`, which is where every provider's request/response quirks are
already isolated.

Tenant scoping: every read here takes `tenant_id` and filters on it (ADR-001). There is
no `_unscoped` variant, unlike lead_service — nothing on a Celery-side path needs to look
up an integration by id today. When Session 2's CRM sync does, it will resolve the
integration from `call.tenant_id`, which it already has, so add
`get_for_tenant`-by-explicit-id rather than an unscoped lookup.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.integration import Integration
from backend.services import integration_service

# What can be connected. Validated here, not as a DB constraint or an Enum column, so
# adding a provider is a one-line change with no migration — the same reasoning behind
# llm_service.MODEL_CATALOG rather than an enum of model names.
#
# "esign" is deliberately absent: we supply the NDA template and send it from our own
# Dropbox Sign account, so that credential is platform config, not a tenant row. See
# models/integration.py.
SUPPORTED: dict[str, set[str]] = {"crm": {"hubspot"}}

# Config keys each provider understands. Unknown keys are rejected rather than stored:
# a typo'd "api_kye" that silently persists reads as "connected" in the UI and then fails
# on the first real sync, which is the failure mode this whole endpoint exists to prevent.
ALLOWED_CONFIG_KEYS: dict[str, set[str]] = {
    "hubspot": {"api_key", "pipeline_id", "stage_id", "portal_id"},
}


class IntegrationConfigError(Exception):
    """The requested integration config is invalid — surfaced as a 422 by the router."""


def validate(kind: str, provider: str, config: dict) -> None:
    if kind not in SUPPORTED:
        raise IntegrationConfigError(
            f"Unsupported integration kind '{kind}'. Supported: {sorted(SUPPORTED)}."
        )
    if provider not in SUPPORTED[kind]:
        raise IntegrationConfigError(
            f"Unsupported {kind} provider '{provider}'. Supported: {sorted(SUPPORTED[kind])}."
        )
    allowed = ALLOWED_CONFIG_KEYS.get(provider, set())
    unknown = sorted(set(config) - allowed)
    if unknown:
        raise IntegrationConfigError(
            f"Unknown config keys for {provider}: {unknown}. Allowed: {sorted(allowed)}."
        )


async def get(db: AsyncSession, tenant_id: uuid.UUID, kind: str) -> Integration | None:
    result = await db.execute(
        select(Integration).where(Integration.tenant_id == tenant_id, Integration.kind == kind)
    )
    return result.scalar_one_or_none()


async def list_for_tenant(db: AsyncSession, tenant_id: uuid.UUID) -> list[Integration]:
    result = await db.execute(
        select(Integration).where(Integration.tenant_id == tenant_id).order_by(Integration.kind)
    )
    return list(result.scalars().all())


async def upsert(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    kind: str,
    provider: str,
    config: dict,
    enabled: bool,
) -> Integration:
    """Create or update the tenant's integration for `kind`.

    `config` MERGES into the stored dict rather than replacing it. Two reasons, both
    learned from how these forms actually get used: a client changing one setting
    shouldn't have to re-send the API key, and a UI that renders the masked secret back
    into its own form field would otherwise save the literal mask over the real key on
    the next save. An explicit empty string clears a key — that's the deliberate way to
    remove one.

    Changing `provider` on an existing row keeps the old provider's config keys out by
    validating the *merged* result, so switching HubSpot -> something else can't leave
    orphaned HubSpot settings behind.
    """
    existing = await get(db, tenant_id, kind)
    merged = dict(existing.config or {}) if existing and existing.provider == provider else {}
    merged.update(config)
    # An empty string means "clear this", not "store an empty credential" — a stored ""
    # would defeat integration_service._require's actionable missing-credential message.
    merged = {k: v for k, v in merged.items() if v != ""}

    validate(kind, provider, merged)

    if existing:
        # Compute this BEFORE assigning, or the comparison is against the value we just
        # wrote and can never be true.
        changed = merged != (existing.config or {}) or existing.provider != provider
        existing.provider = provider
        existing.config = merged
        existing.enabled = enabled
        # Any credential change invalidates the previous verdict. Leaving a stale
        # last_verified_at behind would let a freshly-pasted wrong key look verified.
        if changed:
            existing.last_verified_at = None
            existing.last_verify_error = None
        integration = existing
    else:
        integration = Integration(
            tenant_id=tenant_id, kind=kind, provider=provider, config=merged, enabled=enabled
        )
        db.add(integration)

    await db.commit()
    await db.refresh(integration)
    return integration


async def delete(db: AsyncSession, tenant_id: uuid.UUID, kind: str) -> bool:
    integration = await get(db, tenant_id, kind)
    if not integration:
        return False
    await db.delete(integration)
    await db.commit()
    return True


async def verify(db: AsyncSession, integration: Integration) -> tuple[bool, str]:
    """Check the stored credential against the provider and record the verdict.

    Returns (ok, detail) rather than raising: "your key is wrong" is a successful answer
    to "is my key right?", and the router turns this into a 200 either way.

    The result is persisted (`last_verified_at` / `last_verify_error`) because the useful
    version of this information is historical — when the CRM sync starts failing, "last
    verified three weeks ago" points straight at a rotated key.
    """
    api_key = str((integration.config or {}).get("api_key", ""))
    try:
        if integration.provider == "hubspot":
            await integration_service.verify_hubspot_credentials(api_key)
        else:
            # Unreachable via the router (validate() gates on SUPPORTED) but reachable by
            # a direct service call, and a silent pass would be worse than a clear no.
            raise integration_service.IntegrationError(
                f"No verifier implemented for provider '{integration.provider}'."
            )
    except integration_service.IntegrationError as exc:
        integration.last_verify_error = str(exc)[:2000]
        await db.commit()
        return False, str(exc)

    integration.last_verified_at = datetime.now(UTC)
    integration.last_verify_error = None
    await db.commit()
    return True, f"{integration.provider} credentials accepted."
