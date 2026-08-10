"""Tests for the /api/prospects HTTP surface.

Service-level prospect logic (ranking, upsert-dedupe, research transitions) lives in
tests/test_prospect_service.py — this file covers the router: validation, tenant
scoping, and response shape.
"""

import uuid

import pytest

from backend.services import prospect_service


async def _make_prospect(db_session, tenant_id, name="Acme HVAC", place_id="p_api"):
    [prospect] = await prospect_service.upsert_from_places(
        db_session, tenant_id, [{"google_place_id": place_id, "name": name}], "q"
    )
    return prospect


@pytest.mark.asyncio
async def test_new_prospect_defaults_to_not_called(db_session, tenant_id):
    prospect = await _make_prospect(db_session, tenant_id)
    assert prospect.status == "not_called"


@pytest.mark.asyncio
async def test_patch_sets_status(client, db_session, tenant_id, auth_headers):
    prospect = await _make_prospect(db_session, tenant_id)

    resp = await client.patch(
        f"/api/prospects/{prospect.id}", json={"status": "booked"}, headers=auth_headers
    )

    assert resp.status_code == 200
    assert resp.json()["status"] == "booked"


@pytest.mark.asyncio
async def test_patch_rejects_unknown_status(client, db_session, tenant_id, auth_headers):
    prospect = await _make_prospect(db_session, tenant_id)

    resp = await client.patch(
        f"/api/prospects/{prospect.id}", json={"status": "vibing"}, headers=auth_headers
    )

    assert resp.status_code == 422
    assert "vibing" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_patch_status_does_not_touch_outreach_status(
    client, db_session, tenant_id, auth_headers
):
    """The two axes are independent by design (backend/models/prospect.py) — setting one
    must not silently advance the other.
    """
    prospect = await _make_prospect(db_session, tenant_id)

    resp = await client.patch(
        f"/api/prospects/{prospect.id}", json={"status": "no_answer"}, headers=auth_headers
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "no_answer"
    assert body["outreach_status"] == "not_reached"


@pytest.mark.asyncio
async def test_patch_can_set_both_axes_at_once(client, db_session, tenant_id, auth_headers):
    prospect = await _make_prospect(db_session, tenant_id)

    resp = await client.patch(
        f"/api/prospects/{prospect.id}",
        json={"status": "booked", "outreach_status": "reached"},
        headers=auth_headers,
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "booked"
    assert body["outreach_status"] == "reached"


@pytest.mark.asyncio
async def test_patch_status_is_tenant_scoped(
    client, db_session, other_tenant_id, other_auth_headers
):
    """Another tenant's prospect must 404, not be silently updated (ADR-001)."""
    prospect = await _make_prospect(db_session, uuid.uuid4())

    resp = await client.patch(
        f"/api/prospects/{prospect.id}", json={"status": "booked"}, headers=other_auth_headers
    )

    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_set_status_rejects_other_tenant(db_session, tenant_id, other_tenant_id):
    prospect = await _make_prospect(db_session, tenant_id)

    result = await prospect_service.set_status(
        db_session, prospect.id, other_tenant_id, "do_not_call"
    )

    assert result is None
    unchanged = await prospect_service.get_prospect(db_session, prospect.id, tenant_id)
    assert unchanged.status == "not_called"
