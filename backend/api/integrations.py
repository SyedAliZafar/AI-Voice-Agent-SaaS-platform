"""Integration settings endpoints — connect a tenant's CRM (phase5 Session 1).

This is the repo's first CRUD surface for third-party credentials. Before it, the only
credential store was `ToolConfig`, which has no router at all — rows had to be inserted
by seed script or by hand (see phase4.md Session 2's open gap). That's why the "connect
your CRM" flow starts here rather than extending something.

tenant_id comes from the bearer token via Depends(get_current_tenant) — see
backend/api/deps.py. `kind` is a path param and therefore attacker-controlled, so it is
validated against integration_config_service.SUPPORTED before it reaches a query.

Responses never echo a stored secret; schemas/integration.py masks them.
"""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import get_current_tenant
from backend.database import get_db
from backend.schemas.integration import (
    IntegrationResponse,
    IntegrationTestResult,
    IntegrationUpsert,
)
from backend.services import integration_config_service

router = APIRouter()


@router.get("", response_model=list[IntegrationResponse])
async def list_integrations(
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    integrations = await integration_config_service.list_for_tenant(db, tenant_id)
    return [IntegrationResponse.from_model(i) for i in integrations]


@router.put("/{kind}", response_model=IntegrationResponse)
async def upsert_integration(
    kind: str,
    payload: IntegrationUpsert,
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Connect or reconfigure the tenant's integration for `kind`.

    PUT rather than POST because there is at most one row per (tenant, kind) — the same
    body sent twice must leave the same single connection, not two.

    `config` merges into what's stored, so a client can change the pipeline id without
    resending the API key. See integration_config_service.upsert.
    """
    if payload.kind != kind:
        raise HTTPException(
            status_code=422, detail=f"Body kind '{payload.kind}' does not match path '{kind}'"
        )
    try:
        integration = await integration_config_service.upsert(
            db, tenant_id, kind, payload.provider, payload.config, payload.enabled
        )
    except integration_config_service.IntegrationConfigError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return IntegrationResponse.from_model(integration)


@router.get("/{kind}", response_model=IntegrationResponse)
async def get_integration(
    kind: str,
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    integration = await integration_config_service.get(db, tenant_id, kind)
    if not integration:
        raise HTTPException(status_code=404, detail=f"No {kind} integration configured")
    return IntegrationResponse.from_model(integration)


@router.delete("/{kind}", status_code=204)
async def delete_integration(
    kind: str,
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    deleted = await integration_config_service.delete(db, tenant_id, kind)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"No {kind} integration configured")


@router.post("/{kind}/test", response_model=IntegrationTestResult)
async def test_integration(
    kind: str,
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Check the stored credential against the provider, and record the verdict.

    A rejected credential is a 200 with `ok: false`, not a 4xx — the request succeeded,
    the answer is just "no". Only a missing integration is a 404. Read-only against the
    provider: this never creates a contact.
    """
    integration = await integration_config_service.get(db, tenant_id, kind)
    if not integration:
        raise HTTPException(status_code=404, detail=f"No {kind} integration configured")

    ok, detail = await integration_config_service.verify(db, integration)
    return IntegrationTestResult(
        ok=ok,
        provider=integration.provider,
        detail=detail,
        # Falls back to now() for the failure case, where verify() leaves
        # last_verified_at untouched (a failed check must not look like a successful one).
        checked_at=integration.last_verified_at or datetime.now(UTC),
    )
