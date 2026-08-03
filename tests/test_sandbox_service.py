"""Tests for sandbox_service — the text-chat agent-testing sandbox.

Mocks llm_service.get_agent_response entirely; these tests verify sandbox_service's own
orchestration (prompt override wins, model resolution, tools default off, tenant scoping),
not any real LLM's output.
"""

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from backend.schemas.agent import AgentCreate
from backend.services import agent_service, sandbox_service


@pytest.mark.asyncio
async def test_chat_returns_reply_from_llm_service(db_session, tenant_id):
    agent = await agent_service.create_agent(
        db_session,
        tenant_id,
        AgentCreate(name="Ali", platform="retell", system_prompt="You are Ali."),
    )
    mock_response = AsyncMock(return_value="Hello, how can I help?")

    with patch("backend.services.llm_service.get_agent_response", mock_response):
        result = await sandbox_service.chat(
            db_session, agent.id, tenant_id, [{"role": "user", "content": "Hi"}]
        )

    assert result["reply"] == "Hello, how can I help?"
    mock_response.assert_awaited_once()


@pytest.mark.asyncio
async def test_unknown_agent_raises_sandbox_error(db_session, tenant_id):
    with pytest.raises(sandbox_service.SandboxError):
        await sandbox_service.chat(db_session, uuid.uuid4(), tenant_id, [])


@pytest.mark.asyncio
async def test_another_tenants_agent_raises_sandbox_error(db_session, tenant_id, other_tenant_id):
    agent = await agent_service.create_agent(
        db_session, tenant_id, AgentCreate(name="Mine", platform="retell")
    )
    with pytest.raises(sandbox_service.SandboxError):
        await sandbox_service.chat(db_session, agent.id, other_tenant_id, [])


@pytest.mark.asyncio
async def test_system_prompt_override_wins_over_agent_system_prompt(db_session, tenant_id):
    """Unlike the live custom-LLM path (test_call_service rejects overrides outright),
    the sandbox has an obvious place for a call-time override to live."""
    agent = await agent_service.create_agent(
        db_session,
        tenant_id,
        AgentCreate(name="Ali", platform="retell", system_prompt="Saved prompt"),
    )
    mock_response = AsyncMock(return_value="ok")

    with patch("backend.services.llm_service.get_agent_response", mock_response):
        await sandbox_service.chat(
            db_session,
            agent.id,
            tenant_id,
            [{"role": "user", "content": "Hi"}],
            system_prompt_override="Draft prompt",
        )

    assert mock_response.await_args.args[0] == "Draft prompt"


@pytest.mark.asyncio
async def test_falls_back_to_agent_system_prompt_when_no_override(db_session, tenant_id):
    agent = await agent_service.create_agent(
        db_session,
        tenant_id,
        AgentCreate(name="Ali", platform="retell", system_prompt="Saved prompt"),
    )
    mock_response = AsyncMock(return_value="ok")

    with patch("backend.services.llm_service.get_agent_response", mock_response):
        await sandbox_service.chat(
            db_session, agent.id, tenant_id, [{"role": "user", "content": "Hi"}]
        )

    assert mock_response.await_args.args[0] == "Saved prompt"


@pytest.mark.asyncio
async def test_model_resolution_prefers_explicit_over_agent_over_default(db_session, tenant_id):
    agent = await agent_service.create_agent(
        db_session,
        tenant_id,
        AgentCreate(name="Ali", platform="retell", llm_model="deepseek-reasoner"),
    )
    mock_response = AsyncMock(return_value="ok")

    with patch("backend.services.llm_service.get_agent_response", mock_response):
        # Explicit model wins over the agent's own.
        result = await sandbox_service.chat(
            db_session, agent.id, tenant_id, [{"role": "user", "content": "Hi"}], model="gpt-4o"
        )
    assert result["model"] == "gpt-4o"
    assert mock_response.await_args.kwargs["model"] == "gpt-4o"

    with patch("backend.services.llm_service.get_agent_response", mock_response):
        # No explicit model -> the agent's own llm_model.
        result = await sandbox_service.chat(
            db_session, agent.id, tenant_id, [{"role": "user", "content": "Hi"}]
        )
    assert result["model"] == "deepseek-reasoner"


@pytest.mark.asyncio
async def test_model_falls_back_to_settings_default_when_agent_has_none(db_session, tenant_id):
    agent = await agent_service.create_agent(
        db_session, tenant_id, AgentCreate(name="Ali", platform="retell")
    )
    mock_response = AsyncMock(return_value="ok")

    with (
        patch("backend.services.llm_service.get_agent_response", mock_response),
        patch.object(sandbox_service.settings, "default_llm_model", "deepseek-chat"),
    ):
        result = await sandbox_service.chat(
            db_session, agent.id, tenant_id, [{"role": "user", "content": "Hi"}]
        )
    assert result["model"] == "deepseek-chat"


@pytest.mark.asyncio
async def test_tools_disabled_by_default(db_session, tenant_id):
    agent = await agent_service.create_agent(
        db_session, tenant_id, AgentCreate(name="Ali", platform="retell")
    )
    mock_response = AsyncMock(return_value="ok")

    with patch("backend.services.llm_service.get_agent_response", mock_response):
        result = await sandbox_service.chat(
            db_session, agent.id, tenant_id, [{"role": "user", "content": "Hi"}]
        )

    assert result["tools_enabled"] is False
    assert mock_response.await_args.kwargs["tools_enabled"] is False


@pytest.mark.asyncio
async def test_tools_can_be_enabled_explicitly(db_session, tenant_id):
    agent = await agent_service.create_agent(
        db_session, tenant_id, AgentCreate(name="Ali", platform="retell")
    )
    mock_response = AsyncMock(return_value="ok")

    with patch("backend.services.llm_service.get_agent_response", mock_response):
        result = await sandbox_service.chat(
            db_session,
            agent.id,
            tenant_id,
            [{"role": "user", "content": "Hi"}],
            tools_enabled=True,
        )

    assert result["tools_enabled"] is True
    assert mock_response.await_args.kwargs["tools_enabled"] is True
