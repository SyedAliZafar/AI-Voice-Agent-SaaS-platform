"""Auth enforcement on the HTTP surface.

Phase 0 gate: before this backend can be exposed publicly (which the Retell custom-LLM
websocket requires), every /api/* route must reject unauthenticated callers, and a token
scoped to one tenant must not reach another tenant's data. Prior to backend/api/deps.py,
tenant_id was an unauthenticated query parameter and all of this was wide open.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from jose import jwt

from backend.config import get_settings
from backend.schemas.agent import AgentCreate
from backend.services import agent_service
from tests.conftest import make_token

# Every authenticated route, as (method, path). Webhooks are deliberately excluded —
# see the AUTH note in backend/api/webhooks.py.
PROTECTED_ROUTES = [
    ("get", "/api/agents"),
    ("get", "/api/agents/models"),
    ("post", "/api/agents"),
    ("get", f"/api/agents/{uuid.uuid4()}"),
    ("patch", f"/api/agents/{uuid.uuid4()}"),
    ("delete", f"/api/agents/{uuid.uuid4()}"),
    ("post", f"/api/agents/{uuid.uuid4()}/test-call"),
    ("post", f"/api/agents/{uuid.uuid4()}/sandbox-chat"),
    ("get", "/api/agents/platform"),
    ("post", "/api/agents/platform/call"),
    ("get", "/api/agents/platform/agent_x/variables"),
    ("get", "/api/calls"),
    ("get", f"/api/calls/{uuid.uuid4()}"),
    ("get", f"/api/calls/{uuid.uuid4()}/transcript"),
    ("get", f"/api/calls/{uuid.uuid4()}/events"),
    ("get", "/api/phone-numbers"),
    ("get", "/api/analytics/summary"),
    ("get", "/api/analytics/top-intents"),
    ("get", "/api/prospects"),
    ("post", "/api/prospects/discover"),
    ("post", "/api/prospects/import-csv"),
    ("get", "/api/prospects/stats"),
    ("get", "/api/prospects/city-autocomplete"),
    ("get", f"/api/prospects/{uuid.uuid4()}"),
    ("patch", f"/api/prospects/{uuid.uuid4()}"),
    ("post", f"/api/prospects/{uuid.uuid4()}/research"),
    ("post", f"/api/prospects/{uuid.uuid4()}/call"),
    ("post", f"/api/prospects/{uuid.uuid4()}/sandbox-chat"),
    ("get", "/api/leads"),
    ("post", "/api/leads"),
    ("get", "/api/leads/stats"),
    ("get", f"/api/leads/{uuid.uuid4()}"),
    ("patch", f"/api/leads/{uuid.uuid4()}"),
    ("delete", f"/api/leads/{uuid.uuid4()}"),
    ("post", f"/api/leads/{uuid.uuid4()}/start"),
    ("post", f"/api/leads/{uuid.uuid4()}/pause"),
    ("post", f"/api/leads/{uuid.uuid4()}/do-not-call"),
    ("post", f"/api/leads/{uuid.uuid4()}/call"),
    # Integrations hold third-party credentials, so an unauthenticated read here would be
    # a credential disclosure rather than just a data leak.
    ("get", "/api/integrations"),
    ("get", "/api/integrations/crm"),
    ("put", "/api/integrations/crm"),
    ("delete", "/api/integrations/crm"),
    ("post", "/api/integrations/crm/test"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(("method", "path"), PROTECTED_ROUTES)
async def test_route_rejects_missing_token(client, method, path):
    # client.request() rather than client.get()/.delete() — the latter reject a json body.
    resp = await client.request(method, path, json={})
    assert resp.status_code == 401, f"{method.upper()} {path} allowed an unauthenticated request"


@pytest.mark.asyncio
@pytest.mark.parametrize(("method", "path"), PROTECTED_ROUTES)
async def test_route_rejects_forged_token(client, method, path):
    """A token signed with the wrong key must not be accepted."""
    forged = jwt.encode({"tenant_id": str(uuid.uuid4())}, "not-the-real-secret", algorithm="HS256")
    resp = await client.request(
        method, path, json={}, headers={"Authorization": f"Bearer {forged}"}
    )
    assert resp.status_code == 401, f"{method.upper()} {path} accepted a forged token"


@pytest.mark.asyncio
async def test_rejects_token_without_tenant_claim(client):
    settings = get_settings()
    token = jwt.encode({"sub": "someone"}, settings.jwt_secret, algorithm="HS256")
    resp = await client.get("/api/agents", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_rejects_expired_token(client, tenant_id):
    settings = get_settings()
    past = datetime.now(UTC) - timedelta(hours=2)
    token = jwt.encode(
        {"tenant_id": str(tenant_id), "iat": past, "exp": past + timedelta(hours=1)},
        settings.jwt_secret,
        algorithm="HS256",
    )
    resp = await client.get("/api/agents", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_rejects_non_uuid_tenant_claim(client):
    settings = get_settings()
    token = jwt.encode({"tenant_id": "not-a-uuid"}, settings.jwt_secret, algorithm="HS256")
    resp = await client.get("/api/agents", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_valid_token_is_accepted(client, auth_headers):
    resp = await client.get("/api/agents", headers=auth_headers)
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_health_stays_public(client):
    """The health check must not require a token — load balancers poll it."""
    resp = await client.get("/health")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_agent_list_only_returns_own_tenants_agents(
    client, db_session, tenant_id, other_tenant_id, auth_headers, other_auth_headers
):
    await agent_service.create_agent(
        db_session, tenant_id, AgentCreate(name="Mine", platform="retell")
    )
    await agent_service.create_agent(
        db_session, other_tenant_id, AgentCreate(name="Theirs", platform="retell")
    )

    resp = await client.get("/api/agents", headers=auth_headers)
    assert [a["name"] for a in resp.json()] == ["Mine"]

    resp = await client.get("/api/agents", headers=other_auth_headers)
    assert [a["name"] for a in resp.json()] == ["Theirs"]


@pytest.mark.asyncio
async def test_cannot_read_another_tenants_agent(client, db_session, tenant_id, other_auth_headers):
    agent = await agent_service.create_agent(
        db_session, tenant_id, AgentCreate(name="Mine", platform="retell")
    )

    resp = await client.get(f"/api/agents/{agent.id}", headers=other_auth_headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_cannot_delete_another_tenants_agent(
    client, db_session, tenant_id, other_auth_headers
):
    agent = await agent_service.create_agent(
        db_session, tenant_id, AgentCreate(name="Mine", platform="retell")
    )

    resp = await client.delete(f"/api/agents/{agent.id}", headers=other_auth_headers)
    assert resp.status_code == 204  # idempotent delete
    assert await agent_service.get_agent(db_session, agent.id, tenant_id) is not None


@pytest.mark.asyncio
async def test_cannot_place_test_call_on_another_tenants_agent(
    client, db_session, tenant_id, other_auth_headers
):
    """The costliest cross-tenant action: this endpoint spends real telephony money."""
    agent = await agent_service.create_agent(
        db_session, tenant_id, AgentCreate(name="Mine", platform="retell")
    )

    resp = await client.post(
        f"/api/agents/{agent.id}/test-call",
        json={"to_number": "+15551234567"},
        headers=other_auth_headers,
    )
    assert resp.status_code == 422
    assert "not found" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_cannot_sandbox_chat_with_another_tenants_agent(
    client, db_session, tenant_id, other_auth_headers
):
    agent = await agent_service.create_agent(
        db_session, tenant_id, AgentCreate(name="Mine", platform="retell")
    )

    resp = await client.post(
        f"/api/agents/{agent.id}/sandbox-chat",
        json={"messages": [{"role": "user", "content": "Hi"}]},
        headers=other_auth_headers,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_token_for_one_tenant_does_not_leak_via_creation(
    client, db_session, tenant_id, auth_headers
):
    """Agents are created under the token's tenant, not one the client names."""
    resp = await client.post(
        "/api/agents",
        json={"name": "New", "platform": "retell", "tenant_id": str(uuid.uuid4())},
        headers=auth_headers,
    )
    assert resp.status_code == 201

    agents = await agent_service.list_agents(db_session, tenant_id)
    assert [a.name for a in agents] == ["New"]


@pytest.mark.asyncio
async def test_cannot_read_another_tenants_crm_credentials(
    client, tenant_id, auth_headers, other_auth_headers
):
    """The highest-consequence cross-tenant read on the API: this row holds a live HubSpot
    key. A 404 rather than a 403, same as every other resource, so ids stay
    non-enumerable."""
    await client.put(
        "/api/integrations/crm",
        json={"kind": "crm", "provider": "hubspot", "config": {"api_key": "pat-na1-secret"}},
        headers=auth_headers,
    )

    resp = await client.get("/api/integrations/crm", headers=other_auth_headers)
    assert resp.status_code == 404
    assert "pat-na1-secret" not in resp.text

    listed = await client.get("/api/integrations", headers=other_auth_headers)
    assert listed.json() == []


@pytest.mark.asyncio
async def test_make_token_roundtrips(tenant_id):
    """Guards the test helper itself — a broken minter would make every auth test vacuous."""
    settings = get_settings()
    claims = jwt.decode(make_token(tenant_id), settings.jwt_secret, algorithms=["HS256"])
    assert claims["tenant_id"] == str(tenant_id)
