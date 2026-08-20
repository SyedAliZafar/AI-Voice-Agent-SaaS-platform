"""Tests for agent CRUD endpoints and service logic."""

import uuid

import pytest

from backend.schemas.agent import AgentCreate
from backend.services import agent_service


@pytest.mark.asyncio
async def test_create_agent(db_session, tenant_id):
    payload = AgentCreate(
        name="Sales qualifier", system_prompt="You are helpful.", platform="retell"
    )
    agent = await agent_service.create_agent(db_session, tenant_id, payload)

    assert agent.name == "Sales qualifier"
    assert agent.tenant_id == tenant_id
    assert agent.platform == "retell"


@pytest.mark.asyncio
async def test_get_agent_not_found(db_session, tenant_id):
    agent = await agent_service.get_agent(db_session, uuid.uuid4(), tenant_id)
    assert agent is None


@pytest.mark.asyncio
async def test_get_agent_is_scoped_to_tenant(db_session, tenant_id, other_tenant_id):
    """An agent belonging to another tenant must be invisible, not merely forbidden —
    returning None lets routers 404 so ids stay non-enumerable (ADR-001).
    """
    agent = await agent_service.create_agent(
        db_session, tenant_id, AgentCreate(name="Mine", platform="retell")
    )

    assert await agent_service.get_agent(db_session, agent.id, tenant_id) is not None
    assert await agent_service.get_agent(db_session, agent.id, other_tenant_id) is None


@pytest.mark.asyncio
async def test_update_agent_rejects_other_tenant(db_session, tenant_id, other_tenant_id):
    from backend.schemas.agent import AgentUpdate

    agent = await agent_service.create_agent(
        db_session, tenant_id, AgentCreate(name="Original", platform="retell")
    )

    result = await agent_service.update_agent(
        db_session, agent.id, other_tenant_id, AgentUpdate(name="Hijacked")
    )

    assert result is None
    assert (await agent_service.get_agent(db_session, agent.id, tenant_id)).name == "Original"


@pytest.mark.asyncio
async def test_delete_agent_rejects_other_tenant(db_session, tenant_id, other_tenant_id):
    agent = await agent_service.create_agent(
        db_session, tenant_id, AgentCreate(name="Mine", platform="retell")
    )

    await agent_service.delete_agent(db_session, agent.id, other_tenant_id)

    assert await agent_service.get_agent(db_session, agent.id, tenant_id) is not None


@pytest.mark.asyncio
async def test_list_agents_scoped_to_tenant(db_session, tenant_id):
    other_tenant = uuid.uuid4()
    await agent_service.create_agent(
        db_session, tenant_id, AgentCreate(name="Agent A", platform="retell")
    )
    await agent_service.create_agent(
        db_session, other_tenant, AgentCreate(name="Agent B", platform="vapi")
    )

    agents = await agent_service.list_agents(db_session, tenant_id)

    assert len(agents) == 1
    assert agents[0].name == "Agent A"


@pytest.mark.asyncio
async def test_update_agent_partial(db_session, tenant_id):
    from backend.schemas.agent import AgentUpdate

    agent = await agent_service.create_agent(
        db_session, tenant_id, AgentCreate(name="Original", platform="retell")
    )
    updated = await agent_service.update_agent(
        db_session, agent.id, tenant_id, AgentUpdate(name="Renamed")
    )

    assert updated.name == "Renamed"
    assert updated.platform == "retell"  # unchanged fields preserved


# --- Platform-native agent routes (ADR-012) -----------------------------------


@pytest.mark.asyncio
async def test_list_platform_agents_route_is_not_captured_by_the_uuid_path(client, auth_headers):
    """GET /api/agents/platform must reach its own handler, not /{agent_id}'s uuid
    param — the same route-ordering trap /models and /ambient-sounds document. A 422
    from uuid parsing is what regression looks like here, so assert the real payload.
    """
    from unittest.mock import AsyncMock, patch

    roster = AsyncMock(return_value=[{"external_id": "agent_ext_1", "name": "Roofing"}])
    with patch("backend.services.test_call_service.list_platform_agents", new=roster):
        resp = await client.get("/api/agents/platform", headers=auth_headers)

    assert resp.status_code == 200
    body = resp.json()
    assert body["platform"] == "retell"
    assert body["agents"] == [
        {
            "external_id": "agent_ext_1",
            "name": "Roofing",
            "voice_id": None,
            "engine": None,
            "version": None,
            "last_modified_ms": None,
        }
    ]


@pytest.mark.asyncio
async def test_call_platform_agent_route_validates_the_number_before_dialing(client, auth_headers):
    """Same E.164 rule as the local test-call path — the two dial paths share
    _validate_e164 precisely so they can't drift on what they accept."""
    resp = await client.post(
        "/api/agents/platform/call",
        json={"external_agent_id": "agent_ext_1", "to_number": "0170123456"},
        headers=auth_headers,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_call_platform_agent_route_surfaces_an_unknown_agent_as_422(client, auth_headers):
    from unittest.mock import AsyncMock, patch

    from backend.services import test_call_service

    failing = AsyncMock(side_effect=test_call_service.TestCallError("No agent 'x' on the ..."))
    with patch("backend.services.test_call_service.place_platform_agent_call", new=failing):
        resp = await client.post(
            "/api/agents/platform/call",
            json={"external_agent_id": "x", "to_number": "+491701234567"},
            headers=auth_headers,
        )

    assert resp.status_code == 422
    assert "No agent" in resp.json()["detail"]
