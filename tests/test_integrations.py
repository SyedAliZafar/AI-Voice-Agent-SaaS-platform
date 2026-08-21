"""Tests for the /api/integrations HTTP surface (phase5 Session 1).

Covers what the router itself owns: validation, tenant scoping, the merge-not-replace PUT
semantics, and — the one with real consequences — that a stored secret is never echoed
back in a response.

Provider HTTP shaping (verify_hubspot_credentials' request) lives in
tests/test_integration_service.py, matching how that file already owns Cal.com's wire
format.
"""

from unittest.mock import AsyncMock, patch

import pytest

from backend.schemas.integration import mask_secret
from backend.services import integration_config_service

HUBSPOT_KEY = "pat-na1-0123456789abcdef"


async def _connect_crm(client, auth_headers, **overrides):
    payload = {
        "kind": "crm",
        "provider": "hubspot",
        "config": {"api_key": HUBSPOT_KEY, "pipeline_id": "default"},
        "enabled": True,
    }
    payload.update(overrides)
    return await client.put("/api/integrations/crm", json=payload, headers=auth_headers)


@pytest.mark.asyncio
async def test_connect_crm_creates_integration(client, auth_headers):
    resp = await _connect_crm(client, auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["kind"] == "crm"
    assert body["provider"] == "hubspot"
    assert body["enabled"] is True
    assert body["config"]["pipeline_id"] == "default"
    # Never verified yet — a freshly pasted key must not look checked.
    assert body["last_verified_at"] is None


@pytest.mark.asyncio
async def test_response_never_echoes_the_api_key(client, auth_headers):
    """The whole reason mask_config exists. A GET that returns the key it was given is a
    free way to leak it into a browser cache, a screenshot, or a proxy log."""
    await _connect_crm(client, auth_headers)

    resp = await client.get("/api/integrations/crm", headers=auth_headers)
    body = resp.json()

    assert HUBSPOT_KEY not in resp.text
    assert body["config"]["api_key"] == mask_secret(HUBSPOT_KEY)
    assert body["config"]["api_key"].endswith("cdef")  # last 4 kept, so it's identifiable
    assert body["secrets_set"] == ["api_key"]


@pytest.mark.asyncio
async def test_put_is_idempotent_not_duplicating(client, auth_headers):
    """PUT, not POST: the same body twice must leave one connection, not two. The
    (tenant_id, kind) unique constraint is the backstop, this is the behavior."""
    first = await _connect_crm(client, auth_headers)
    second = await _connect_crm(client, auth_headers)

    assert first.json()["id"] == second.json()["id"]
    listed = await client.get("/api/integrations", headers=auth_headers)
    assert len(listed.json()) == 1


@pytest.mark.asyncio
async def test_config_merges_so_a_partial_update_keeps_the_key(
    client, auth_headers, tenant_id, db_session
):
    """Changing the pipeline id must not wipe the API key — a UI that only sends the
    field it edited is the normal case, and a replace would silently disconnect the CRM."""
    await _connect_crm(client, auth_headers)

    resp = await client.put(
        "/api/integrations/crm",
        json={"kind": "crm", "provider": "hubspot", "config": {"pipeline_id": "sales-2"}},
        headers=auth_headers,
    )

    assert resp.status_code == 200
    assert resp.json()["config"]["pipeline_id"] == "sales-2"
    assert resp.json()["secrets_set"] == ["api_key"]

    # And the stored value is still the real key, not the mask — asserted against the row
    # rather than the response, since the response is masked by design.
    stored = await integration_config_service.get(db_session, tenant_id, "crm")
    assert stored.config["api_key"] == HUBSPOT_KEY


@pytest.mark.asyncio
async def test_empty_string_clears_a_config_key(client, auth_headers):
    """An explicit "" is how you remove a credential. Storing it verbatim would defeat
    integration_service._require's actionable missing-credential message."""
    await _connect_crm(client, auth_headers)

    resp = await client.put(
        "/api/integrations/crm",
        json={"kind": "crm", "provider": "hubspot", "config": {"api_key": ""}},
        headers=auth_headers,
    )

    assert resp.json()["secrets_set"] == []
    assert "api_key" not in resp.json()["config"]


@pytest.mark.asyncio
async def test_rejects_unknown_provider(client, auth_headers):
    resp = await _connect_crm(client, auth_headers, provider="salesforce")
    assert resp.status_code == 422
    assert "salesforce" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_rejects_unknown_kind(client, auth_headers):
    resp = await client.put(
        "/api/integrations/esign",
        json={"kind": "esign", "provider": "hubspot", "config": {}},
        headers=auth_headers,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_rejects_typoed_config_key(client, auth_headers):
    """A stored "api_kye" would read as connected in the UI and fail on the first real
    sync — exactly the failure this endpoint exists to prevent."""
    resp = await _connect_crm(client, auth_headers, config={"api_kye": HUBSPOT_KEY})
    assert resp.status_code == 422
    assert "api_kye" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_body_kind_must_match_path(client, auth_headers):
    resp = await client.put(
        "/api/integrations/crm",
        json={"kind": "esign", "provider": "hubspot", "config": {}},
        headers=auth_headers,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_integrations_are_tenant_scoped(client, auth_headers, other_auth_headers):
    """ADR-001. One tenant's CRM credentials must be invisible to another's."""
    await _connect_crm(client, auth_headers)

    assert (await client.get("/api/integrations", headers=other_auth_headers)).json() == []
    theirs = await client.get("/api/integrations/crm", headers=other_auth_headers)
    assert theirs.status_code == 404


@pytest.mark.asyncio
async def test_two_tenants_can_each_connect_crm(client, auth_headers, other_auth_headers):
    """The unique constraint is on (tenant_id, kind) — it must not be a global one-CRM
    limit."""
    assert (await _connect_crm(client, auth_headers)).status_code == 200
    assert (await _connect_crm(client, other_auth_headers)).status_code == 200


@pytest.mark.asyncio
async def test_get_missing_integration_is_404(client, auth_headers):
    assert (await client.get("/api/integrations/crm", headers=auth_headers)).status_code == 404


@pytest.mark.asyncio
async def test_delete_removes_the_integration(client, auth_headers):
    await _connect_crm(client, auth_headers)
    assert (await client.delete("/api/integrations/crm", headers=auth_headers)).status_code == 204
    assert (await client.get("/api/integrations/crm", headers=auth_headers)).status_code == 404


@pytest.mark.asyncio
async def test_delete_missing_integration_is_404(client, auth_headers):
    assert (await client.delete("/api/integrations/crm", headers=auth_headers)).status_code == 404


@pytest.mark.asyncio
async def test_test_endpoint_records_success(client, auth_headers):
    await _connect_crm(client, auth_headers)

    with patch(
        "backend.services.integration_service.verify_hubspot_credentials",
        new=AsyncMock(return_value=None),
    ):
        resp = await client.post("/api/integrations/crm/test", headers=auth_headers)

    assert resp.status_code == 200
    assert resp.json()["ok"] is True

    # Persisted, not just returned: "last verified three weeks ago" is what points at a
    # rotated key when the sync starts failing.
    stored = await client.get("/api/integrations/crm", headers=auth_headers)
    assert stored.json()["last_verified_at"] is not None
    assert stored.json()["last_verify_error"] is None


@pytest.mark.asyncio
async def test_bad_credentials_are_a_200_with_ok_false(client, auth_headers):
    """ "Your key is wrong" is a successful answer to "is my key right?". Only a missing
    integration is a 4xx."""
    from backend.services.integration_service import IntegrationError

    await _connect_crm(client, auth_headers)

    with patch(
        "backend.services.integration_service.verify_hubspot_credentials",
        new=AsyncMock(side_effect=IntegrationError("HubSpot returned HTTP 401: expired")),
    ):
        resp = await client.post("/api/integrations/crm/test", headers=auth_headers)

    assert resp.status_code == 200
    assert resp.json()["ok"] is False
    assert "401" in resp.json()["detail"]

    stored = await client.get("/api/integrations/crm", headers=auth_headers)
    assert stored.json()["last_verified_at"] is None
    assert "expired" in stored.json()["last_verify_error"]


@pytest.mark.asyncio
async def test_changing_the_key_clears_a_previous_verification(client, auth_headers):
    """Otherwise a freshly pasted wrong key inherits the old key's green tick."""
    await _connect_crm(client, auth_headers)
    with patch(
        "backend.services.integration_service.verify_hubspot_credentials",
        new=AsyncMock(return_value=None),
    ):
        await client.post("/api/integrations/crm/test", headers=auth_headers)
    assert (await client.get("/api/integrations/crm", headers=auth_headers)).json()[
        "last_verified_at"
    ] is not None

    await _connect_crm(client, auth_headers, config={"api_key": "pat-na1-different"})

    assert (await client.get("/api/integrations/crm", headers=auth_headers)).json()[
        "last_verified_at"
    ] is None


@pytest.mark.asyncio
async def test_test_endpoint_on_missing_integration_is_404(client, auth_headers):
    resp = await client.post("/api/integrations/crm/test", headers=auth_headers)
    assert resp.status_code == 404


def test_mask_secret_keeps_short_values_fully_hidden():
    """An 8-char secret's last 4 is half of it — no tail for anything that short."""
    assert mask_secret("short12") == "•" * 8
    assert mask_secret("") == ""
    assert mask_secret("pat-na1-0123456789abcdef").endswith("cdef")
