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
