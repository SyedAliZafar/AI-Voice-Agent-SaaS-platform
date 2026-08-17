"""Tests for the /api/leads HTTP surface (ADR-011).

Service-level scheduler logic (backoff math, outcome evaluation) lives in
tests/test_lead_service.py — this file covers the router: validation, tenant scoping,
and the create-paused / start / pause / do-not-call lifecycle.
"""

import uuid

import pytest

from backend.schemas.agent import AgentCreate
from backend.services import agent_service, lead_service


async def _create_lead(client, auth_headers, **overrides):
    payload = {"phone": "+491701111111", "business_name": "Acme HVAC", "source": "bark"}
    payload.update(overrides)
    resp = await client.post("/api/leads", json=payload, headers=auth_headers)
    return resp


@pytest.mark.asyncio
async def test_create_lead_lands_paused(client, auth_headers):
    resp = await _create_lead(client, auth_headers)
    assert resp.status_code == 201
    body = resp.json()
    assert body["retry_state"] == "paused"
    assert body["status"] == "new"
    assert body["attempt_count"] == 0


@pytest.mark.asyncio
async def test_create_lead_requires_phone(client, auth_headers):
    resp = await client.post(
        "/api/leads", json={"business_name": "No Phone Co"}, headers=auth_headers
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_list_leads_is_tenant_scoped(client, auth_headers, other_auth_headers):
    await _create_lead(client, auth_headers)
    await _create_lead(client, other_auth_headers, phone="+491702222222")

    resp = await client.get("/api/leads", headers=auth_headers)
    assert resp.status_code == 200
    assert len(resp.json()) == 1


@pytest.mark.asyncio
async def test_stats_counts_by_retry_state(client, auth_headers):
    a = (await _create_lead(client, auth_headers)).json()
    await _create_lead(client, auth_headers, phone="+491703333333")
    await client.post(f"/api/leads/{a['id']}/start", headers=auth_headers)

    resp = await client.get("/api/leads/stats", headers=auth_headers)
    body = resp.json()
    assert body["total"] == 2
    assert body["paused"] == 1
    assert body["scheduled"] == 1


@pytest.mark.asyncio
async def test_patch_updates_notes_and_details(client, auth_headers):
    lead = (await _create_lead(client, auth_headers)).json()

    resp = await client.patch(
        f"/api/leads/{lead['id']}",
        json={"notes": "Owner only answers after 5pm.", "details": {"boiler_age": "12 years"}},
        headers=auth_headers,
    )

    assert resp.status_code == 200
    assert resp.json()["notes"] == "Owner only answers after 5pm."
    assert resp.json()["details"] == {"boiler_age": "12 years"}


@pytest.mark.asyncio
async def test_patch_rejects_unknown_status(client, auth_headers):
    lead = (await _create_lead(client, auth_headers)).json()

    resp = await client.patch(
        f"/api/leads/{lead['id']}", json={"status": "vibing"}, headers=auth_headers
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_start_then_pause_round_trip(client, auth_headers):
    lead = (await _create_lead(client, auth_headers)).json()

    started = await client.post(f"/api/leads/{lead['id']}/start", headers=auth_headers)
    assert started.json()["retry_state"] == "scheduled"
    assert started.json()["next_attempt_at"] is not None

    paused = await client.post(f"/api/leads/{lead['id']}/pause", headers=auth_headers)
    assert paused.json()["retry_state"] == "paused"
    assert paused.json()["next_attempt_at"] is None


@pytest.mark.asyncio
async def test_do_not_call_is_terminal(client, auth_headers):
    lead = (await _create_lead(client, auth_headers)).json()

    resp = await client.post(f"/api/leads/{lead['id']}/do-not-call", headers=auth_headers)
    assert resp.json()["retry_state"] == "do_not_call"


@pytest.mark.asyncio
async def test_delete_removes_the_lead(client, auth_headers):
    lead = (await _create_lead(client, auth_headers)).json()

    resp = await client.delete(f"/api/leads/{lead['id']}", headers=auth_headers)
    assert resp.status_code == 204

    resp = await client.get(f"/api/leads/{lead['id']}", headers=auth_headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_operations_on_another_tenants_lead_404(client, auth_headers, other_auth_headers):
    lead = (await _create_lead(client, auth_headers)).json()

    resp = await client.get(f"/api/leads/{lead['id']}", headers=other_auth_headers)
    assert resp.status_code == 404
    resp = await client.post(f"/api/leads/{lead['id']}/start", headers=other_auth_headers)
    assert resp.status_code == 404


@pytest.fixture
def placed_calls(monkeypatch) -> list[dict]:
    from backend.services import test_call_service

    calls: list[dict] = []

    async def fake_place_test_call(
        db, agent_id, tenant_id, to_number, system_prompt_override=None, lead_id=None
    ):
        calls.append(
            {"agent_id": agent_id, "to_number": to_number, "prompt": system_prompt_override}
        )
        return {
            "call_id": f"mock_call_{len(calls)}",
            "from_number": "+10000000000",
            "status": "dialing",
        }

    monkeypatch.setattr(test_call_service, "place_test_call", fake_place_test_call)
    return calls


@pytest.mark.asyncio
async def test_call_now_dials_immediately_and_bumps_attempt_count(
    client, db_session, tenant_id, auth_headers, placed_calls
):
    agent = await agent_service.create_agent(
        db_session, tenant_id, AgentCreate(name="SDR", system_prompt="Hi.", platform="retell")
    )
    lead = (await _create_lead(client, auth_headers, agent_id=str(agent.id))).json()

    resp = await client.post(f"/api/leads/{lead['id']}/call", json={}, headers=auth_headers)

    assert resp.status_code == 200
    assert placed_calls[0]["to_number"] == "+491701111111"

    refreshed = await lead_service.get_lead(db_session, uuid.UUID(lead["id"]), tenant_id)
    assert refreshed.attempt_count == 1
    assert refreshed.retry_state == "in_flight"


@pytest.mark.asyncio
async def test_call_now_without_agent_is_a_422(client, auth_headers, placed_calls):
    lead = (await _create_lead(client, auth_headers)).json()

    resp = await client.post(f"/api/leads/{lead['id']}/call", json={}, headers=auth_headers)
    assert resp.status_code == 422
