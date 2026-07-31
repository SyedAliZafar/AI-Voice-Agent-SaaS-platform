"""Tests for the outbound test-call orchestration.

Mocks RetellAdapter entirely — verifies our provisioning/caching logic, not
Retell's actual API. See backend/services/test_call_service.py.
"""

from unittest.mock import AsyncMock, patch

import pytest

from backend.schemas.agent import AgentCreate
from backend.services import agent_service, test_call_service


@pytest.mark.asyncio
async def test_place_test_call_requires_from_number(db_session, tenant_id):
    agent = await agent_service.create_agent(
        db_session, tenant_id, AgentCreate(name="SDR", platform="retell", system_prompt="Hi")
    )

    with patch("backend.services.test_call_service.settings") as mock_settings:
        mock_settings.retell_from_number = ""
        with pytest.raises(test_call_service.TestCallError, match="RETELL_FROM_NUMBER"):
            await test_call_service.place_test_call(
                db_session, agent.id, tenant_id, "+491701234567"
            )


@pytest.mark.asyncio
async def test_place_test_call_rejects_non_retell_agent(db_session, tenant_id):
    agent = await agent_service.create_agent(
        db_session, tenant_id, AgentCreate(name="SDR", platform="vapi", system_prompt="Hi")
    )

    with pytest.raises(test_call_service.TestCallError, match="Retell agents only"):
        await test_call_service.place_test_call(db_session, agent.id, tenant_id, "+491701234567")


@pytest.mark.asyncio
async def test_place_test_call_provisions_and_caches_retell_ids(db_session, tenant_id):
    agent = await agent_service.create_agent(
        db_session, tenant_id, AgentCreate(name="SDR", platform="retell", system_prompt="Pitch v1")
    )

    mock_adapter = AsyncMock()
    mock_adapter.create_llm.return_value = "llm_123"
    mock_adapter.create_agent_with_llm.return_value = "agent_ext_123"
    mock_adapter.create_outbound_call.return_value = "call_abc"

    with (
        patch("backend.services.test_call_service.settings") as mock_settings,
        patch("backend.services.test_call_service.RetellAdapter", return_value=mock_adapter),
    ):
        mock_settings.retell_from_number = "+15551234567"
        mock_settings.retell_default_voice_id = "11labs-Adrian"

        result = await test_call_service.place_test_call(
            db_session, agent.id, tenant_id, "+491701234567"
        )

    assert result == {"call_id": "call_abc", "from_number": "+15551234567", "status": "dialing"}
    mock_adapter.create_llm.assert_awaited_once_with("Pitch v1")
    mock_adapter.create_agent_with_llm.assert_awaited_once()
    mock_adapter.create_outbound_call.assert_awaited_once_with(
        from_number="+15551234567", to_number="+491701234567", agent_external_id="agent_ext_123"
    )

    # ids are cached on the agent for reuse
    refreshed = await agent_service.get_agent(db_session, agent.id, tenant_id)
    assert refreshed.voice_config["retell"] == {"llm_id": "llm_123", "agent_id": "agent_ext_123"}

    # a Call row is created immediately (status in_progress), so outbound calls
    # show up in the Calls list / dashboard without waiting on a webhook.
    from backend.services import call_service

    calls = await call_service.list_calls(db_session, tenant_id, None, None, 50, 0)
    assert len(calls) == 1
    assert calls[0].external_id == "call_abc"
    assert calls[0].status == "in_progress"
    assert calls[0].caller_number == "+491701234567"


@pytest.mark.asyncio
async def test_place_test_call_reuses_cached_ids_and_updates_prompt(db_session, tenant_id):
    agent = await agent_service.create_agent(
        db_session, tenant_id, AgentCreate(name="SDR", platform="retell", system_prompt="Pitch v2")
    )
    agent.voice_config = {"retell": {"llm_id": "llm_existing", "agent_id": "agent_existing"}}
    await db_session.commit()

    mock_adapter = AsyncMock()
    mock_adapter.create_outbound_call.return_value = "call_xyz"

    with (
        patch("backend.services.test_call_service.settings") as mock_settings,
        patch("backend.services.test_call_service.RetellAdapter", return_value=mock_adapter),
    ):
        mock_settings.retell_from_number = "+15551234567"

        await test_call_service.place_test_call(db_session, agent.id, tenant_id, "+491701234567")

    mock_adapter.update_llm.assert_awaited_once_with("llm_existing", "Pitch v2")
    mock_adapter.create_llm.assert_not_awaited()
    mock_adapter.create_agent_with_llm.assert_not_awaited()
    mock_adapter.create_outbound_call.assert_awaited_once_with(
        from_number="+15551234567", to_number="+491701234567", agent_external_id="agent_existing"
    )


@pytest.mark.asyncio
async def test_place_test_call_override_does_not_persist_to_agent(db_session, tenant_id):
    """Per-prospect personalized prompts are call-time only — the campaign's base
    system_prompt in the DB must not be overwritten by a personalized variant.
    """
    agent = await agent_service.create_agent(
        db_session,
        tenant_id,
        AgentCreate(name="SDR", platform="retell", system_prompt="Base script"),
    )

    mock_adapter = AsyncMock()
    mock_adapter.create_llm.return_value = "llm_1"
    mock_adapter.create_agent_with_llm.return_value = "agent_1"
    mock_adapter.create_outbound_call.return_value = "call_1"

    with (
        patch("backend.services.test_call_service.settings") as mock_settings,
        patch("backend.services.test_call_service.RetellAdapter", return_value=mock_adapter),
    ):
        mock_settings.retell_from_number = "+15551234567"
        mock_settings.retell_default_voice_id = "11labs-Adrian"

        await test_call_service.place_test_call(
            db_session,
            agent.id,
            tenant_id,
            "+491701234567",
            system_prompt_override="Base script\n[COMPANY BRIEF] personalized for Acme",
        )

    mock_adapter.create_llm.assert_awaited_once_with(
        "Base script\n[COMPANY BRIEF] personalized for Acme"
    )

    refreshed = await agent_service.get_agent(db_session, agent.id, tenant_id)
    assert refreshed.system_prompt == "Base script"  # unchanged in the DB


@pytest.mark.asyncio
async def test_place_test_call_custom_llm_provisions_and_caches(db_session, tenant_id):
    agent = await agent_service.create_agent(
        db_session,
        tenant_id,
        AgentCreate(name="SDR", platform="retell", system_prompt="Hi", use_custom_llm=True),
    )

    mock_adapter = AsyncMock()
    mock_adapter.create_agent_with_custom_llm.return_value = "custom_agent_1"
    mock_adapter.create_outbound_call.return_value = "call_custom_1"

    with (
        patch("backend.services.test_call_service.settings") as mock_settings,
        patch("backend.services.test_call_service.RetellAdapter", return_value=mock_adapter),
    ):
        mock_settings.retell_from_number = "+15551234567"
        mock_settings.retell_default_voice_id = "11labs-Adrian"
        mock_settings.public_base_url = "https://abc123.trycloudflare.com"

        result = await test_call_service.place_test_call(
            db_session, agent.id, tenant_id, "+491701234567"
        )

    assert result == {
        "call_id": "call_custom_1",
        "from_number": "+15551234567",
        "status": "dialing",
    }
    mock_adapter.create_agent_with_custom_llm.assert_awaited_once_with(
        name="SDR",
        llm_websocket_url="wss://abc123.trycloudflare.com/llm-websocket",
        voice_id="11labs-Adrian",
    )
    mock_adapter.create_llm.assert_not_awaited()
    mock_adapter.create_outbound_call.assert_awaited_once_with(
        from_number="+15551234567",
        to_number="+491701234567",
        agent_external_id="custom_agent_1",
    )

    refreshed = await agent_service.get_agent(db_session, agent.id, tenant_id)
    assert refreshed.voice_config["retell_custom"] == {
        "agent_id": "custom_agent_1",
        "ws_url": "wss://abc123.trycloudflare.com/llm-websocket",
    }


@pytest.mark.asyncio
async def test_place_test_call_custom_llm_requires_public_base_url(db_session, tenant_id):
    agent = await agent_service.create_agent(
        db_session,
        tenant_id,
        AgentCreate(name="SDR", platform="retell", system_prompt="Hi", use_custom_llm=True),
    )

    with patch("backend.services.test_call_service.settings") as mock_settings:
        mock_settings.retell_from_number = "+15551234567"
        mock_settings.public_base_url = ""
        with pytest.raises(test_call_service.TestCallError, match="PUBLIC_BASE_URL"):
            await test_call_service.place_test_call(
                db_session, agent.id, tenant_id, "+491701234567"
            )


@pytest.mark.asyncio
async def test_place_test_call_custom_llm_rejects_prompt_override(db_session, tenant_id):
    agent = await agent_service.create_agent(
        db_session,
        tenant_id,
        AgentCreate(name="SDR", platform="retell", system_prompt="Hi", use_custom_llm=True),
    )

    with patch("backend.services.test_call_service.settings") as mock_settings:
        mock_settings.retell_from_number = "+15551234567"
        mock_settings.public_base_url = "https://abc123.trycloudflare.com"
        with pytest.raises(test_call_service.TestCallError, match="use_custom_llm"):
            await test_call_service.place_test_call(
                db_session,
                agent.id,
                tenant_id,
                "+491701234567",
                system_prompt_override="Personalized for Acme",
            )


@pytest.mark.asyncio
async def test_place_test_call_custom_llm_reprovisions_on_tunnel_change(db_session, tenant_id):
    """A cached agent_id from a previous (now-dead) tunnel URL must trigger
    re-provisioning rather than silently pointing Retell at a stale websocket.
    """
    agent = await agent_service.create_agent(
        db_session,
        tenant_id,
        AgentCreate(name="SDR", platform="retell", system_prompt="Hi", use_custom_llm=True),
    )
    agent.voice_config = {
        "retell_custom": {
            "agent_id": "stale_agent",
            "ws_url": "wss://old-tunnel.trycloudflare.com/llm-websocket",
        }
    }
    await db_session.commit()

    mock_adapter = AsyncMock()
    mock_adapter.create_agent_with_custom_llm.return_value = "fresh_agent"
    mock_adapter.create_outbound_call.return_value = "call_fresh"

    with (
        patch("backend.services.test_call_service.settings") as mock_settings,
        patch("backend.services.test_call_service.RetellAdapter", return_value=mock_adapter),
    ):
        mock_settings.retell_from_number = "+15551234567"
        mock_settings.retell_default_voice_id = "11labs-Adrian"
        mock_settings.public_base_url = "https://new-tunnel.trycloudflare.com"

        await test_call_service.place_test_call(db_session, agent.id, tenant_id, "+491701234567")

    mock_adapter.create_agent_with_custom_llm.assert_awaited_once_with(
        name="SDR",
        llm_websocket_url="wss://new-tunnel.trycloudflare.com/llm-websocket",
        voice_id="11labs-Adrian",
    )
    mock_adapter.create_outbound_call.assert_awaited_once_with(
        from_number="+15551234567",
        to_number="+491701234567",
        agent_external_id="fresh_agent",
    )
