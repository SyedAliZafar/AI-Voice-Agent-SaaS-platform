"""Tests for the outbound test-call orchestration.

Mocks RetellAdapter entirely — verifies our provisioning/caching logic, not
Retell's actual API. See backend/services/test_call_service.py.
"""

from unittest.mock import AsyncMock, patch

import pytest

from backend.schemas.agent import AgentCreate
from backend.services import agent_service, call_service, test_call_service


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
        # No tunnel — the hosted path must still work, just without lifecycle webhooks.
        mock_settings.public_base_url = ""

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
    assert refreshed.voice_config["retell"] == {
        "llm_id": "llm_123",
        "agent_id": "agent_ext_123",
        "webhook_url": None,
    }

    # a Call row is created immediately (status in_progress), so outbound calls
    # show up in the Calls list / dashboard without waiting on a webhook.
    from backend.services import call_service

    calls = await call_service.list_calls(db_session, tenant_id, None, None, 50, 0)
    assert len(calls) == 1
    assert calls[0].external_id == "call_abc"
    assert calls[0].status == "in_progress"
    assert calls[0].caller_number == "+491701234567"


@pytest.mark.asyncio
async def test_place_test_call_registers_webhook_url_when_public_url_set(db_session, tenant_id):
    """Retell needs a webhook_url to send call_ended — without it, calls never leave
    in_progress. Registered at agent-creation time from PUBLIC_BASE_URL.
    """
    agent = await agent_service.create_agent(
        db_session, tenant_id, AgentCreate(name="SDR", platform="retell", system_prompt="Pitch")
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
        mock_settings.public_base_url = "https://abc123.trycloudflare.com"

        await test_call_service.place_test_call(db_session, agent.id, tenant_id, "+491701234567")

    mock_adapter.create_agent_with_llm.assert_awaited_once_with(
        name="SDR",
        llm_id="llm_1",
        voice_id="11labs-Adrian",
        webhook_url="https://abc123.trycloudflare.com/webhooks/retell",
    )


@pytest.mark.asyncio
async def test_place_test_call_reprovisions_when_webhook_url_changes(db_session, tenant_id):
    """A Retell agent's webhook_url is fixed at creation. An agent provisioned before
    PUBLIC_BASE_URL was set (or under a since-restarted tunnel) would otherwise keep
    pointing at a dead/absent webhook forever, and its calls would never resolve.
    """
    agent = await agent_service.create_agent(
        db_session, tenant_id, AgentCreate(name="SDR", platform="retell", system_prompt="Pitch")
    )
    agent.voice_config = {
        "retell": {
            "llm_id": "llm_existing",
            "agent_id": "agent_stale",
            "webhook_url": None,  # provisioned back when no tunnel existed
        }
    }
    await db_session.commit()

    mock_adapter = AsyncMock()
    mock_adapter.create_agent_with_llm.return_value = "agent_fresh"
    mock_adapter.create_outbound_call.return_value = "call_1"

    with (
        patch("backend.services.test_call_service.settings") as mock_settings,
        patch("backend.services.test_call_service.RetellAdapter", return_value=mock_adapter),
    ):
        mock_settings.retell_from_number = "+15551234567"
        mock_settings.retell_default_voice_id = "11labs-Adrian"
        mock_settings.public_base_url = "https://now-tunnelled.trycloudflare.com"

        await test_call_service.place_test_call(db_session, agent.id, tenant_id, "+491701234567")

    # The LLM is reused (prompt just updated) but the AGENT is recreated with the webhook.
    mock_adapter.update_llm.assert_awaited_once_with("llm_existing", "Pitch")
    mock_adapter.create_agent_with_llm.assert_awaited_once_with(
        name="SDR",
        llm_id="llm_existing",
        voice_id="11labs-Adrian",
        webhook_url="https://now-tunnelled.trycloudflare.com/webhooks/retell",
    )
    mock_adapter.create_outbound_call.assert_awaited_once_with(
        from_number="+15551234567", to_number="+491701234567", agent_external_id="agent_fresh"
    )


@pytest.mark.asyncio
async def test_place_test_call_reprovisions_when_cached_llm_was_deleted(db_session, tenant_id):
    """An LLM deleted in Retell's dashboard leaves our cached llm_id pointing at nothing.

    Before update_llm reported that (rather than raising on the 404) this was permanent:
    every subsequent call 500'd on the same dead id and no code path could replace it.
    The agent must be recreated too — its response_engine still names the deleted LLM.
    """
    agent = await agent_service.create_agent(
        db_session, tenant_id, AgentCreate(name="SDR", platform="retell", system_prompt="Pitch")
    )
    agent.voice_config = {
        "retell": {
            "llm_id": "llm_deleted_upstream",
            "agent_id": "agent_pointing_at_it",
            "webhook_url": None,
        }
    }
    await db_session.commit()

    mock_adapter = AsyncMock()
    mock_adapter.update_llm.return_value = False  # Retell 404 — it's gone
    mock_adapter.create_llm.return_value = "llm_fresh"
    mock_adapter.create_agent_with_llm.return_value = "agent_fresh"
    mock_adapter.create_outbound_call.return_value = "call_1"

    with (
        patch("backend.services.test_call_service.settings") as mock_settings,
        patch("backend.services.test_call_service.RetellAdapter", return_value=mock_adapter),
    ):
        mock_settings.retell_from_number = "+15551234567"
        mock_settings.retell_default_voice_id = "11labs-Adrian"
        mock_settings.public_base_url = ""

        await test_call_service.place_test_call(db_session, agent.id, tenant_id, "+491701234567")

    mock_adapter.create_llm.assert_awaited_once_with("Pitch")
    mock_adapter.create_agent_with_llm.assert_awaited_once_with(
        name="SDR",
        llm_id="llm_fresh",
        voice_id="11labs-Adrian",
        webhook_url=None,
    )
    mock_adapter.create_outbound_call.assert_awaited_once_with(
        from_number="+15551234567", to_number="+491701234567", agent_external_id="agent_fresh"
    )

    await db_session.refresh(agent)
    assert agent.voice_config["retell"]["llm_id"] == "llm_fresh"
    assert agent.voice_config["retell"]["agent_id"] == "agent_fresh"


@pytest.mark.asyncio
async def test_place_web_call_needs_no_from_number(db_session, tenant_id):
    """The demo path: no phone number is dialed, so RETELL_FROM_NUMBER is irrelevant.

    place_test_call raises without it; this must not, or a demo would depend on
    telephony config it never uses.
    """
    agent = await agent_service.create_agent(
        db_session,
        tenant_id,
        AgentCreate(name="Receptionist", platform="retell", system_prompt="Hi"),
    )

    mock_adapter = AsyncMock()
    mock_adapter.create_llm.return_value = "llm_1"
    mock_adapter.create_agent_with_llm.return_value = "agent_1"
    mock_adapter.create_web_call.return_value = {
        "call_id": "call_web_1",
        "access_token": "tok_abc",
    }

    with (
        patch("backend.services.test_call_service.settings") as mock_settings,
        patch("backend.services.test_call_service.RetellAdapter", return_value=mock_adapter),
    ):
        mock_settings.retell_from_number = ""  # deliberately unset
        mock_settings.retell_default_voice_id = "11labs-Adrian"
        mock_settings.public_base_url = ""

        result = await test_call_service.place_web_call(db_session, agent.id, tenant_id)

    assert result["access_token"] == "tok_abc"
    assert result["call_id"] == "call_web_1"
    mock_adapter.create_web_call.assert_awaited_once_with(agent_external_id="agent_1")
    # No phone call was placed on the web path.
    mock_adapter.create_outbound_call.assert_not_awaited()


@pytest.mark.asyncio
async def test_place_platform_agent_web_call_blocks_unfilled_placeholders(db_session, tenant_id):
    """An unfilled {{placeholder}} is read out loud verbatim. On the demo path that means
    saying it to the client the demo is for, so the call must be refused, not attempted.
    """
    mock_adapter = AsyncMock()
    mock_adapter.list_platform_agents.return_value = [
        {"external_id": "agent_ext", "name": "Marissa"}
    ]
    mock_adapter.get_agent_dynamic_variables.return_value = ["company_name", "contact_name"]

    with patch("backend.services.test_call_service.get_adapter", return_value=mock_adapter):
        with pytest.raises(test_call_service.TestCallError, match="contact_name"):
            await test_call_service.place_platform_agent_web_call(
                db_session,
                tenant_id,
                "agent_ext",
                dynamic_variables={"company_name": "Acme"},
            )

    mock_adapter.create_web_call.assert_not_awaited()


@pytest.mark.asyncio
async def test_place_platform_agent_web_call_sends_only_declared_variables(db_session, tenant_id):
    """Extras are harmless to Retell but make the audit trail read as though the agent
    used data it never saw — so only what the prompt declares is sent.
    """
    mock_adapter = AsyncMock()
    mock_adapter.list_platform_agents.return_value = [
        {"external_id": "agent_ext", "name": "Marissa"}
    ]
    mock_adapter.get_agent_dynamic_variables.return_value = ["company_name"]
    mock_adapter.create_web_call.return_value = {
        "call_id": "call_web_9",
        "access_token": "tok_xyz",
    }

    with patch("backend.services.test_call_service.get_adapter", return_value=mock_adapter):
        result = await test_call_service.place_platform_agent_web_call(
            db_session,
            tenant_id,
            "agent_ext",
            dynamic_variables={"company_name": "Acme", "not_in_prompt": "ignored"},
        )

    assert result["agent_name"] == "Marissa"
    assert result["access_token"] == "tok_xyz"
    mock_adapter.create_web_call.assert_awaited_once_with(
        agent_external_id="agent_ext",
        dynamic_variables={"company_name": "Acme"},
    )

    # Recorded against the platform agent, with no local agent_id (ADR-012).
    calls = await call_service.list_calls(db_session, tenant_id, None, None, 50, 0)
    assert calls[0].external_agent_id == "agent_ext"
    assert calls[0].agent_id is None
    assert calls[0].caller_number == "web"


@pytest.mark.asyncio
async def test_place_platform_agent_web_call_rejects_unknown_agent(db_session, tenant_id):
    mock_adapter = AsyncMock()
    mock_adapter.list_platform_agents.return_value = [
        {"external_id": "agent_other", "name": "Someone else"}
    ]

    with patch("backend.services.test_call_service.get_adapter", return_value=mock_adapter):
        with pytest.raises(test_call_service.TestCallError, match="No agent 'agent_ext'"):
            await test_call_service.place_platform_agent_web_call(
                db_session, tenant_id, "agent_ext"
            )

    mock_adapter.create_web_call.assert_not_awaited()


@pytest.mark.asyncio
async def test_place_test_call_reuses_cached_ids_and_updates_prompt(db_session, tenant_id):
    agent = await agent_service.create_agent(
        db_session, tenant_id, AgentCreate(name="SDR", platform="retell", system_prompt="Pitch v2")
    )
    agent.voice_config = {
        "retell": {"llm_id": "llm_existing", "agent_id": "agent_existing", "webhook_url": None}
    }
    await db_session.commit()

    mock_adapter = AsyncMock()
    mock_adapter.create_outbound_call.return_value = "call_xyz"

    with (
        patch("backend.services.test_call_service.settings") as mock_settings,
        patch("backend.services.test_call_service.RetellAdapter", return_value=mock_adapter),
    ):
        mock_settings.retell_from_number = "+15551234567"
        # Unchanged from what the agent was provisioned with, so no re-provision.
        mock_settings.public_base_url = ""

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
        patch(
            "backend.services.tunnel_check.check_public_url_reachable",
            new=AsyncMock(return_value=None),
        ),
    ):
        mock_settings.retell_from_number = "+15551234567"
        mock_settings.retell_default_voice_id = "11labs-Adrian"
        mock_settings.public_base_url = "https://abc123.trycloudflare.com"
        mock_settings.greeting_delay_ms = 1500
        mock_settings.retell_interruption_sensitivity = 0.3
        mock_settings.retell_responsiveness = 0.7
        mock_settings.retell_ambient_sound = None
        mock_settings.retell_expressive_mode = True
        mock_settings.retell_expressive_emotion_tags = [
            "emphasis",
            "curious",
            "empathetic",
            "pause",
        ]

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
        webhook_url="https://abc123.trycloudflare.com/webhooks/retell",
        # ADR-010: the opening pause has to be Retell's parameter — our websocket opens
        # during call setup, so we can't tell ringing from pickup on our side.
        begin_message_delay_ms=1500,
        # The other half of barge-in control: retell_ws's guard stops US cancelling,
        # this stops Retell chopping audio we already sent (call fae0d38c).
        interruption_sensitivity=0.3,
        responsiveness=0.7,
        ambient_sound=None,
        expressive_mode=True,
        expressive_emotion_tags=["emphasis", "curious", "empathetic", "pause"],
    )
    mock_adapter.create_llm.assert_not_awaited()
    mock_adapter.create_outbound_call.assert_awaited_once_with(
        from_number="+15551234567",
        to_number="+491701234567",
        agent_external_id="custom_agent_1",
    )

    refreshed = await agent_service.get_agent(db_session, agent.id, tenant_id)
    # Every creation-time setting is cached, not just the URLs: a changed value has to
    # miss this key and force a new agent, or it silently never reaches Retell.
    assert refreshed.voice_config["retell_custom"] == {
        "agent_id": "custom_agent_1",
        "ws_url": "wss://abc123.trycloudflare.com/llm-websocket",
        "webhook_url": "https://abc123.trycloudflare.com/webhooks/retell",
        "begin_message_delay_ms": 1500,
        "voice_id": "11labs-Adrian",
        "interruption_sensitivity": 0.3,
        "responsiveness": 0.7,
        "ambient_sound": None,
        "expressive_mode": True,
        "expressive_emotion_tags": ["emphasis", "curious", "empathetic", "pause"],
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
async def test_place_test_call_custom_llm_persists_prompt_override_on_call(db_session, tenant_id):
    """A personalized prospect call on the custom-LLM path can't push its prompt to
    Retell (our websocket answers, not Retell's LLM), so the override has to land on the
    Call row for retell_ws.py to read back by external_id. The agent's own saved script
    stays untouched, and nothing prospect-specific is baked into the provisioned Retell
    agent — same contract the hosted path already had, different delivery route.
    """
    agent = await agent_service.create_agent(
        db_session,
        tenant_id,
        AgentCreate(name="SDR", platform="retell", system_prompt="Hi", use_custom_llm=True),
    )

    mock_adapter = AsyncMock()
    mock_adapter.create_agent_with_custom_llm.return_value = "custom_agent_1"
    mock_adapter.create_outbound_call.return_value = "call_personalized_1"

    with (
        patch("backend.services.test_call_service.settings") as mock_settings,
        patch("backend.services.test_call_service.RetellAdapter", return_value=mock_adapter),
        patch(
            "backend.services.tunnel_check.check_public_url_reachable",
            new=AsyncMock(return_value=None),
        ),
    ):
        mock_settings.retell_from_number = "+15551234567"
        mock_settings.retell_default_voice_id = "11labs-Adrian"
        mock_settings.public_base_url = "https://abc123.trycloudflare.com"
        mock_settings.greeting_delay_ms = 1500
        mock_settings.retell_interruption_sensitivity = 0.3
        mock_settings.retell_responsiveness = 0.7
        mock_settings.retell_ambient_sound = None
        mock_settings.retell_expressive_mode = True
        mock_settings.retell_expressive_emotion_tags = [
            "emphasis",
            "curious",
            "empathetic",
            "pause",
        ]

        await test_call_service.place_test_call(
            db_session,
            agent.id,
            tenant_id,
            "+491701234567",
            system_prompt_override="Hi\n[COMPANY BRIEF] personalized for Acme",
        )

    call = await call_service.get_call_by_external_id(db_session, "call_personalized_1")
    assert call.system_prompt_override == "Hi\n[COMPANY BRIEF] personalized for Acme"

    # The Retell-side agent must stay generic — no prompt is pushed on this path at all.
    mock_adapter.create_llm.assert_not_awaited()
    mock_adapter.update_llm.assert_not_awaited()

    refreshed = await agent_service.get_agent(db_session, agent.id, tenant_id)
    assert refreshed.system_prompt == "Hi"  # unchanged in the DB


@pytest.mark.asyncio
async def test_place_test_call_hosted_llm_does_not_persist_prompt_override_on_call(
    db_session, tenant_id
):
    """The hosted path already delivered the override to Retell at provisioning time.
    Storing it on the Call row too would wrongly imply the websocket should honor it —
    for an agent whose calls never reach the websocket.
    """
    agent = await agent_service.create_agent(
        db_session,
        tenant_id,
        AgentCreate(name="SDR", platform="retell", system_prompt="Base script"),
    )

    mock_adapter = AsyncMock()
    mock_adapter.create_llm.return_value = "llm_1"
    mock_adapter.create_agent_with_llm.return_value = "agent_1"
    mock_adapter.create_outbound_call.return_value = "call_hosted_personalized_1"

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

    call = await call_service.get_call_by_external_id(db_session, "call_hosted_personalized_1")
    assert call.system_prompt_override is None


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
            "webhook_url": "https://old-tunnel.trycloudflare.com/webhooks/retell",
        }
    }
    await db_session.commit()

    mock_adapter = AsyncMock()
    mock_adapter.create_agent_with_custom_llm.return_value = "fresh_agent"
    mock_adapter.create_outbound_call.return_value = "call_fresh"

    with (
        patch("backend.services.test_call_service.settings") as mock_settings,
        patch("backend.services.test_call_service.RetellAdapter", return_value=mock_adapter),
        patch(
            "backend.services.tunnel_check.check_public_url_reachable",
            new=AsyncMock(return_value=None),
        ),
    ):
        mock_settings.retell_from_number = "+15551234567"
        mock_settings.retell_default_voice_id = "11labs-Adrian"
        mock_settings.public_base_url = "https://new-tunnel.trycloudflare.com"
        mock_settings.greeting_delay_ms = 1500
        mock_settings.retell_interruption_sensitivity = 0.3
        mock_settings.retell_responsiveness = 0.7
        mock_settings.retell_ambient_sound = None
        mock_settings.retell_expressive_mode = True
        mock_settings.retell_expressive_emotion_tags = [
            "emphasis",
            "curious",
            "empathetic",
            "pause",
        ]

        await test_call_service.place_test_call(db_session, agent.id, tenant_id, "+491701234567")

    mock_adapter.create_agent_with_custom_llm.assert_awaited_once_with(
        name="SDR",
        llm_websocket_url="wss://new-tunnel.trycloudflare.com/llm-websocket",
        voice_id="11labs-Adrian",
        webhook_url="https://new-tunnel.trycloudflare.com/webhooks/retell",
        begin_message_delay_ms=1500,
        interruption_sensitivity=0.3,
        responsiveness=0.7,
        ambient_sound=None,
        expressive_mode=True,
        expressive_emotion_tags=["emphasis", "curious", "empathetic", "pause"],
    )
    mock_adapter.create_outbound_call.assert_awaited_once_with(
        from_number="+15551234567",
        to_number="+491701234567",
        agent_external_id="fresh_agent",
    )


@pytest.mark.asyncio
async def test_place_test_call_custom_llm_reprovisions_when_greeting_delay_changes(
    db_session, tenant_id
):
    """begin_message_delay_ms is fixed on the Retell agent at creation, so a cached
    agent provisioned before the setting existed (or with a different value) has to be
    recreated — otherwise tuning the opening pause would silently do nothing."""
    agent = await agent_service.create_agent(
        db_session,
        tenant_id,
        AgentCreate(name="SDR", platform="retell", system_prompt="Hi", use_custom_llm=True),
    )
    agent.voice_config = {
        "retell_custom": {
            "agent_id": "agent_without_delay",
            "ws_url": "wss://abc123.trycloudflare.com/llm-websocket",
            "webhook_url": "https://abc123.trycloudflare.com/webhooks/retell",
        }
    }
    await db_session.commit()

    mock_adapter = AsyncMock()
    mock_adapter.create_agent_with_custom_llm.return_value = "agent_with_delay"
    mock_adapter.create_outbound_call.return_value = "call_delay"

    with (
        patch("backend.services.test_call_service.settings") as mock_settings,
        patch("backend.services.test_call_service.RetellAdapter", return_value=mock_adapter),
        patch(
            "backend.services.tunnel_check.check_public_url_reachable",
            new=AsyncMock(return_value=None),
        ),
    ):
        mock_settings.retell_from_number = "+15551234567"
        mock_settings.retell_default_voice_id = "11labs-Adrian"
        mock_settings.public_base_url = "https://abc123.trycloudflare.com"
        mock_settings.greeting_delay_ms = 2000
        mock_settings.retell_interruption_sensitivity = 0.3
        mock_settings.retell_responsiveness = 0.7
        mock_settings.retell_ambient_sound = None
        mock_settings.retell_expressive_mode = True
        mock_settings.retell_expressive_emotion_tags = [
            "emphasis",
            "curious",
            "empathetic",
            "pause",
        ]

        await test_call_service.place_test_call(db_session, agent.id, tenant_id, "+491701234567")

    mock_adapter.create_agent_with_custom_llm.assert_awaited_once()
    assert (
        mock_adapter.create_agent_with_custom_llm.await_args.kwargs["begin_message_delay_ms"]
        == 2000
    )
    refreshed = await agent_service.get_agent(db_session, agent.id, tenant_id)
    assert refreshed.voice_config["retell_custom"]["agent_id"] == "agent_with_delay"


@pytest.mark.asyncio
async def test_place_test_call_custom_llm_reprovisions_when_voice_or_sensitivity_changes(
    db_session, tenant_id
):
    """Regression for call fae0d38c: voice_id and interruption_sensitivity are fixed on
    the Retell agent at creation, but neither was in the provisioning cache key. A cached
    agent was therefore reused forever — the call ran on 11labs-Adrian at Retell's default
    sensitivity while the operator was editing a *different* agent in Retell's dashboard
    and wondering why nothing changed. Changing either must mint a new agent.
    """
    agent = await agent_service.create_agent(
        db_session,
        tenant_id,
        AgentCreate(name="SDR", platform="retell", system_prompt="Hi", use_custom_llm=True),
    )
    agent.voice_config = {
        "retell_custom": {
            "agent_id": "agent_old_voice",
            "ws_url": "wss://abc123.trycloudflare.com/llm-websocket",
            "webhook_url": "https://abc123.trycloudflare.com/webhooks/retell",
            "begin_message_delay_ms": 1500,
            "voice_id": "11labs-Adrian",
            "interruption_sensitivity": 1.0,
        }
    }
    await db_session.commit()

    mock_adapter = AsyncMock()
    mock_adapter.create_agent_with_custom_llm.return_value = "agent_new_voice"
    mock_adapter.create_outbound_call.return_value = "call_voice"

    with (
        patch("backend.services.test_call_service.settings") as mock_settings,
        patch("backend.services.test_call_service.RetellAdapter", return_value=mock_adapter),
        patch(
            "backend.services.tunnel_check.check_public_url_reachable",
            new=AsyncMock(return_value=None),
        ),
    ):
        mock_settings.retell_from_number = "+15551234567"
        mock_settings.retell_default_voice_id = "retell-Maren"
        mock_settings.public_base_url = "https://abc123.trycloudflare.com"
        mock_settings.greeting_delay_ms = 1500
        mock_settings.retell_interruption_sensitivity = 0.3
        mock_settings.retell_responsiveness = 0.7
        mock_settings.retell_ambient_sound = None
        mock_settings.retell_expressive_mode = True
        mock_settings.retell_expressive_emotion_tags = [
            "emphasis",
            "curious",
            "empathetic",
            "pause",
        ]

        await test_call_service.place_test_call(db_session, agent.id, tenant_id, "+491701234567")

    mock_adapter.create_agent_with_custom_llm.assert_awaited_once()
    kwargs = mock_adapter.create_agent_with_custom_llm.await_args.kwargs
    assert kwargs["voice_id"] == "retell-Maren"
    assert kwargs["interruption_sensitivity"] == 0.3
    refreshed = await agent_service.get_agent(db_session, agent.id, tenant_id)
    assert refreshed.voice_config["retell_custom"]["agent_id"] == "agent_new_voice"


@pytest.mark.asyncio
async def test_place_test_call_custom_llm_reprovisions_when_responsiveness_or_ambient_changes(
    db_session, tenant_id
):
    """Same failure mode as the voice/sensitivity regression above, for the two settings
    added right after it: responsiveness and ambient_sound are also fixed on the Retell
    agent at creation, so both must be in the cache key too, or tuning either would
    silently do nothing on a call that already has a cached agent.
    """
    agent = await agent_service.create_agent(
        db_session,
        tenant_id,
        AgentCreate(name="SDR", platform="retell", system_prompt="Hi", use_custom_llm=True),
    )
    agent.voice_config = {
        "retell_custom": {
            "agent_id": "agent_no_ambience",
            "ws_url": "wss://abc123.trycloudflare.com/llm-websocket",
            "webhook_url": "https://abc123.trycloudflare.com/webhooks/retell",
            "begin_message_delay_ms": 1500,
            "voice_id": "retell-Maren",
            "interruption_sensitivity": 0.5,
            "responsiveness": None,
            "ambient_sound": None,
        }
    }
    await db_session.commit()

    mock_adapter = AsyncMock()
    mock_adapter.create_agent_with_custom_llm.return_value = "agent_with_ambience"
    mock_adapter.create_outbound_call.return_value = "call_ambience"

    with (
        patch("backend.services.test_call_service.settings") as mock_settings,
        patch("backend.services.test_call_service.RetellAdapter", return_value=mock_adapter),
        patch(
            "backend.services.tunnel_check.check_public_url_reachable",
            new=AsyncMock(return_value=None),
        ),
    ):
        mock_settings.retell_from_number = "+15551234567"
        mock_settings.retell_default_voice_id = "retell-Maren"
        mock_settings.public_base_url = "https://abc123.trycloudflare.com"
        mock_settings.greeting_delay_ms = 1500
        mock_settings.retell_interruption_sensitivity = 0.5
        mock_settings.retell_responsiveness = 0.7
        mock_settings.retell_ambient_sound = "coffee-shop"
        mock_settings.retell_expressive_mode = True
        mock_settings.retell_expressive_emotion_tags = [
            "emphasis",
            "curious",
            "empathetic",
            "pause",
        ]

        await test_call_service.place_test_call(db_session, agent.id, tenant_id, "+491701234567")

    mock_adapter.create_agent_with_custom_llm.assert_awaited_once()
    kwargs = mock_adapter.create_agent_with_custom_llm.await_args.kwargs
    assert kwargs["responsiveness"] == 0.7
    assert kwargs["ambient_sound"] == "coffee-shop"
    refreshed = await agent_service.get_agent(db_session, agent.id, tenant_id)
    assert refreshed.voice_config["retell_custom"]["agent_id"] == "agent_with_ambience"


@pytest.mark.asyncio
async def test_place_test_call_custom_llm_reprovisions_when_expressive_settings_change(
    db_session, tenant_id
):
    """Same failure mode again, for expressive_mode/expressive_emotion_tags: verified via
    a disposable probe agent that Retell's schema accepts these for retell-Maren, but
    accepted-at-creation is exactly the trap this whole cache key exists to catch — a
    value not in the key just gets silently ignored on every subsequent call.
    """
    agent = await agent_service.create_agent(
        db_session,
        tenant_id,
        AgentCreate(name="SDR", platform="retell", system_prompt="Hi", use_custom_llm=True),
    )
    agent.voice_config = {
        "retell_custom": {
            "agent_id": "agent_flat_delivery",
            "ws_url": "wss://abc123.trycloudflare.com/llm-websocket",
            "webhook_url": "https://abc123.trycloudflare.com/webhooks/retell",
            "begin_message_delay_ms": 1500,
            "voice_id": "retell-Maren",
            "interruption_sensitivity": 0.5,
            "responsiveness": 0.7,
            "ambient_sound": None,
            "expressive_mode": False,
            "expressive_emotion_tags": [],
        }
    }
    await db_session.commit()

    mock_adapter = AsyncMock()
    mock_adapter.create_agent_with_custom_llm.return_value = "agent_expressive"
    mock_adapter.create_outbound_call.return_value = "call_expressive"

    with (
        patch("backend.services.test_call_service.settings") as mock_settings,
        patch("backend.services.test_call_service.RetellAdapter", return_value=mock_adapter),
        patch(
            "backend.services.tunnel_check.check_public_url_reachable",
            new=AsyncMock(return_value=None),
        ),
    ):
        mock_settings.retell_from_number = "+15551234567"
        mock_settings.retell_default_voice_id = "retell-Maren"
        mock_settings.public_base_url = "https://abc123.trycloudflare.com"
        mock_settings.greeting_delay_ms = 1500
        mock_settings.retell_interruption_sensitivity = 0.5
        mock_settings.retell_responsiveness = 0.7
        mock_settings.retell_ambient_sound = None
        mock_settings.retell_expressive_mode = True
        mock_settings.retell_expressive_emotion_tags = [
            "emphasis",
            "curious",
            "empathetic",
            "pause",
        ]

        await test_call_service.place_test_call(db_session, agent.id, tenant_id, "+491701234567")

    mock_adapter.create_agent_with_custom_llm.assert_awaited_once()
    kwargs = mock_adapter.create_agent_with_custom_llm.await_args.kwargs
    assert kwargs["expressive_mode"] is True
    assert kwargs["expressive_emotion_tags"] == ["emphasis", "curious", "empathetic", "pause"]
    refreshed = await agent_service.get_agent(db_session, agent.id, tenant_id)
    assert refreshed.voice_config["retell_custom"]["agent_id"] == "agent_expressive"


@pytest.mark.asyncio
async def test_place_test_call_custom_llm_per_agent_ambient_sound_overrides_default(
    db_session, tenant_id
):
    """voice_config["ambientSound"] is the per-agent override the dashboard's Ambient
    sound picker writes (backend/api/agents.py's generic PATCH .../{agent_id}, same
    mechanism voiceId already uses) — it must win over settings.retell_ambient_sound.
    """
    agent = await agent_service.create_agent(
        db_session,
        tenant_id,
        AgentCreate(name="SDR", platform="retell", system_prompt="Hi", use_custom_llm=True),
    )
    agent.voice_config = {"ambientSound": "call-center"}
    await db_session.commit()

    mock_adapter = AsyncMock()
    mock_adapter.create_agent_with_custom_llm.return_value = "agent_call_center"
    mock_adapter.create_outbound_call.return_value = "call_1"

    with (
        patch("backend.services.test_call_service.settings") as mock_settings,
        patch("backend.services.test_call_service.RetellAdapter", return_value=mock_adapter),
        patch(
            "backend.services.tunnel_check.check_public_url_reachable",
            new=AsyncMock(return_value=None),
        ),
    ):
        mock_settings.retell_from_number = "+15551234567"
        mock_settings.retell_default_voice_id = "retell-Maren"
        mock_settings.public_base_url = "https://abc123.trycloudflare.com"
        mock_settings.greeting_delay_ms = 1500
        mock_settings.retell_interruption_sensitivity = 0.5
        mock_settings.retell_responsiveness = 0.7
        # The global default is silence — the per-agent override must still win.
        mock_settings.retell_ambient_sound = None
        mock_settings.retell_expressive_mode = True
        mock_settings.retell_expressive_emotion_tags = [
            "emphasis",
            "curious",
            "empathetic",
            "pause",
        ]

        await test_call_service.place_test_call(db_session, agent.id, tenant_id, "+491701234567")

    kwargs = mock_adapter.create_agent_with_custom_llm.await_args.kwargs
    assert kwargs["ambient_sound"] == "call-center"


@pytest.mark.asyncio
async def test_place_test_call_custom_llm_per_agent_ambient_sound_can_force_silence(
    db_session, tenant_id
):
    """The other half of the tri-state: an agent can explicitly override to `null`
    (silence) even if the fleet-wide default is later changed to a real sound — this is
    what distinguishes voice_config lacking the key (inherit) from voice_config having
    the key set to None (explicit silence), and is exactly why the resolution in
    test_call_service uses a sentinel instead of `dict.get(key, default)`.
    """
    agent = await agent_service.create_agent(
        db_session,
        tenant_id,
        AgentCreate(name="SDR", platform="retell", system_prompt="Hi", use_custom_llm=True),
    )
    agent.voice_config = {"ambientSound": None}
    await db_session.commit()

    mock_adapter = AsyncMock()
    mock_adapter.create_agent_with_custom_llm.return_value = "agent_silent"
    mock_adapter.create_outbound_call.return_value = "call_1"

    with (
        patch("backend.services.test_call_service.settings") as mock_settings,
        patch("backend.services.test_call_service.RetellAdapter", return_value=mock_adapter),
        patch(
            "backend.services.tunnel_check.check_public_url_reachable",
            new=AsyncMock(return_value=None),
        ),
    ):
        mock_settings.retell_from_number = "+15551234567"
        mock_settings.retell_default_voice_id = "retell-Maren"
        mock_settings.public_base_url = "https://abc123.trycloudflare.com"
        mock_settings.greeting_delay_ms = 1500
        mock_settings.retell_interruption_sensitivity = 0.5
        mock_settings.retell_responsiveness = 0.7
        # Fleet default is a real sound this time — the agent's explicit None must win.
        mock_settings.retell_ambient_sound = "coffee-shop"
        mock_settings.retell_expressive_mode = True
        mock_settings.retell_expressive_emotion_tags = [
            "emphasis",
            "curious",
            "empathetic",
            "pause",
        ]

        await test_call_service.place_test_call(db_session, agent.id, tenant_id, "+491701234567")

    kwargs = mock_adapter.create_agent_with_custom_llm.await_args.kwargs
    assert kwargs["ambient_sound"] is None


@pytest.mark.asyncio
async def test_place_test_call_custom_llm_fails_fast_when_tunnel_unreachable(db_session, tenant_id):
    """A quick tunnel's hostname can stop resolving, or the tunnel can die while
    `docker compose ps` still reports it as Up (see RUN.md/CONTEXT.md ADR-007) — Retell
    would then dial a websocket it can't reach and the caller gets dead air. This must be
    caught before a real, billed call is placed, not after.
    """
    agent = await agent_service.create_agent(
        db_session,
        tenant_id,
        AgentCreate(name="SDR", platform="retell", system_prompt="Hi", use_custom_llm=True),
    )

    mock_adapter = AsyncMock()

    with (
        patch("backend.services.test_call_service.settings") as mock_settings,
        patch("backend.services.test_call_service.RetellAdapter", return_value=mock_adapter),
        patch(
            "backend.services.tunnel_check.check_public_url_reachable",
            new=AsyncMock(
                return_value="cannot connect to https://dead-tunnel.trycloudflare.com/health"
            ),
        ),
    ):
        mock_settings.retell_from_number = "+15551234567"
        mock_settings.public_base_url = "https://dead-tunnel.trycloudflare.com"

        with pytest.raises(test_call_service.TestCallError, match="not reachable"):
            await test_call_service.place_test_call(
                db_session, agent.id, tenant_id, "+491701234567"
            )

    # The whole point: no agent provisioned, no call dialed, no telephony spend.
    mock_adapter.create_agent_with_custom_llm.assert_not_awaited()
    mock_adapter.create_outbound_call.assert_not_awaited()


@pytest.mark.asyncio
async def test_place_test_call_custom_llm_auto_self_heals_after_tunnel_restart(
    db_session, tenant_id
):
    """PUBLIC_BASE_URL=auto: the quick tunnel restarted and minted a new hostname while
    this process held the old one cached. The preflight should fail against the stale
    URL, re-ask cloudflared once, and succeed against the fresh one — turning a tunnel
    restart into a non-event instead of a failed call plus a manual .env edit. This is
    the entire reason "auto" exists.
    """
    agent = await agent_service.create_agent(
        db_session,
        tenant_id,
        AgentCreate(name="SDR", platform="retell", system_prompt="Hi", use_custom_llm=True),
    )

    mock_adapter = AsyncMock()
    mock_adapter.create_agent_with_custom_llm.return_value = "agent_custom_1"
    mock_adapter.create_outbound_call.return_value = "call_1"

    # First resolve returns the stale host, the forced refresh returns the live one.
    resolved = AsyncMock(
        side_effect=[
            "https://stale-tunnel.trycloudflare.com",
            "https://fresh-tunnel.trycloudflare.com",
            "https://fresh-tunnel.trycloudflare.com",  # _webhook_url
        ]
    )
    # Unreachable for the stale host, reachable once we're on the fresh one.
    reachable = AsyncMock(
        side_effect=lambda url, *a, **kw: None if "fresh" in url else "cannot connect"
    )

    with (
        patch("backend.services.test_call_service.settings") as mock_settings,
        patch("backend.services.test_call_service.RetellAdapter", return_value=mock_adapter),
        patch("backend.services.public_url.get_public_base_url", new=resolved),
        patch("backend.services.tunnel_check.check_public_url_reachable", new=reachable),
    ):
        mock_settings.retell_from_number = "+15551234567"
        mock_settings.retell_default_voice_id = "11labs-Adrian"
        mock_settings.public_base_url = "auto"
        mock_settings.greeting_delay_ms = 1500
        mock_settings.retell_interruption_sensitivity = 0.3
        mock_settings.retell_responsiveness = 0.7
        mock_settings.retell_ambient_sound = None
        mock_settings.retell_expressive_mode = True
        mock_settings.retell_expressive_emotion_tags = [
            "emphasis",
            "curious",
            "empathetic",
            "pause",
        ]

        result = await test_call_service.place_test_call(
            db_session, agent.id, tenant_id, "+491701234567"
        )

    assert result["status"] == "dialing"
    # Retell must be pointed at the FRESH tunnel, not the stale cached one.
    kwargs = mock_adapter.create_agent_with_custom_llm.await_args.kwargs
    assert kwargs["llm_websocket_url"] == "wss://fresh-tunnel.trycloudflare.com/llm-websocket"
    # And the refresh was actually forced rather than re-reading the same cached value.
    assert resolved.await_args_list[1].kwargs.get("force_refresh") is True


@pytest.mark.asyncio
async def test_place_test_call_custom_llm_non_auto_does_not_retry(db_session, tenant_id):
    """The self-heal is auto-only. With a literal URL there's nothing to re-discover, so
    a dead tunnel must still fail fast rather than silently probing twice."""
    agent = await agent_service.create_agent(
        db_session,
        tenant_id,
        AgentCreate(name="SDR", platform="retell", system_prompt="Hi", use_custom_llm=True),
    )
    mock_adapter = AsyncMock()
    reachable = AsyncMock(return_value="cannot connect")

    with (
        patch("backend.services.test_call_service.settings") as mock_settings,
        patch("backend.services.test_call_service.RetellAdapter", return_value=mock_adapter),
        patch("backend.services.tunnel_check.check_public_url_reachable", new=reachable),
    ):
        mock_settings.retell_from_number = "+15551234567"
        mock_settings.public_base_url = "https://dead-tunnel.trycloudflare.com"

        with pytest.raises(test_call_service.TestCallError, match="not reachable"):
            await test_call_service.place_test_call(
                db_session, agent.id, tenant_id, "+491701234567"
            )

    assert reachable.await_count == 1


@pytest.mark.asyncio
async def test_place_test_call_hosted_llm_ignores_tunnel_reachability(db_session, tenant_id):
    """The hosted-LLM path is designed to work with no tunnel at all (lifecycle events
    just don't arrive until POST /api/calls/sync) — it must not start requiring one.
    """
    agent = await agent_service.create_agent(
        db_session, tenant_id, AgentCreate(name="SDR", platform="retell", system_prompt="Hi")
    )

    mock_adapter = AsyncMock()
    mock_adapter.create_llm.return_value = "llm_1"
    mock_adapter.create_agent_with_llm.return_value = "agent_1"
    mock_adapter.create_outbound_call.return_value = "call_1"
    unreachable = AsyncMock(return_value="cannot connect (unused on this path)")

    with (
        patch("backend.services.test_call_service.settings") as mock_settings,
        patch("backend.services.test_call_service.RetellAdapter", return_value=mock_adapter),
        patch("backend.services.tunnel_check.check_public_url_reachable", new=unreachable),
    ):
        mock_settings.retell_from_number = "+15551234567"
        mock_settings.retell_default_voice_id = "11labs-Adrian"
        mock_settings.public_base_url = "https://dead-tunnel.trycloudflare.com"

        result = await test_call_service.place_test_call(
            db_session, agent.id, tenant_id, "+491701234567"
        )

    assert result["status"] == "dialing"
    unreachable.assert_not_awaited()


# --- Platform-native agents (ADR-012) -----------------------------------------
# The path that dials an agent built in Retell's own dashboard: no provisioning, no
# prompt push, no tunnel. What these assert is mostly what does NOT happen.


@pytest.mark.asyncio
async def test_place_platform_agent_call_provisions_nothing(db_session, tenant_id):
    mock_adapter = AsyncMock()
    mock_adapter.list_platform_agents.return_value = [
        {"external_id": "agent_ext_9", "name": "Roofing Agent Test Case #1"}
    ]
    mock_adapter.get_agent_dynamic_variables.return_value = []
    mock_adapter.create_outbound_call.return_value = "call_ext_9"

    with (
        patch("backend.services.test_call_service.settings") as mock_settings,
        patch("backend.services.test_call_service.get_adapter", return_value=mock_adapter),
    ):
        mock_settings.retell_from_number = "+15551234567"
        result = await test_call_service.place_platform_agent_call(
            db_session, tenant_id, "agent_ext_9", "+491701234567"
        )

    assert result == {
        "call_id": "call_ext_9",
        "from_number": "+15551234567",
        "status": "dialing",
        "agent_name": "Roofing Agent Test Case #1",
    }
    mock_adapter.create_outbound_call.assert_awaited_once_with(
        from_number="+15551234567",
        to_number="+491701234567",
        agent_external_id="agent_ext_9",
        dynamic_variables={},
    )
    # The whole point of this path: we do not touch the agent's configuration.
    mock_adapter.create_llm.assert_not_awaited()
    mock_adapter.create_agent_with_llm.assert_not_awaited()
    mock_adapter.create_agent_with_custom_llm.assert_not_awaited()


@pytest.mark.asyncio
async def test_place_platform_agent_call_records_call_without_local_agent(db_session, tenant_id):
    """External calls must still land in call history — otherwise half the operator's
    calls are invisible to their own dashboard.
    """
    mock_adapter = AsyncMock()
    mock_adapter.list_platform_agents.return_value = [
        {"external_id": "agent_ext_9", "name": "Roofing"}
    ]
    mock_adapter.get_agent_dynamic_variables.return_value = []
    mock_adapter.create_outbound_call.return_value = "call_ext_9"

    with (
        patch("backend.services.test_call_service.settings") as mock_settings,
        patch("backend.services.test_call_service.get_adapter", return_value=mock_adapter),
    ):
        mock_settings.retell_from_number = "+15551234567"
        await test_call_service.place_platform_agent_call(
            db_session, tenant_id, "agent_ext_9", "+491701234567"
        )

    call = await call_service.get_call_by_external_id(db_session, "call_ext_9")
    assert call is not None
    assert call.tenant_id == tenant_id
    assert call.agent_id is None
    assert call.external_agent_id == "agent_ext_9"
    assert call.status == "in_progress"
    # Nothing here can personalize a single call — the platform's agent holds the script.
    assert call.system_prompt_override is None


@pytest.mark.asyncio
async def test_place_platform_agent_call_rejects_unknown_agent(db_session, tenant_id):
    """A typo'd or deleted id must fail before spending a dial, not surface as an opaque
    Retell 4xx — and it's the guard stopping a raw client-supplied id reaching the API.
    """
    mock_adapter = AsyncMock()
    mock_adapter.list_platform_agents.return_value = [
        {"external_id": "agent_ext_9", "name": "Roofing"}
    ]

    with (
        patch("backend.services.test_call_service.settings") as mock_settings,
        patch("backend.services.test_call_service.get_adapter", return_value=mock_adapter),
    ):
        mock_settings.retell_from_number = "+15551234567"
        with pytest.raises(test_call_service.TestCallError, match="No agent 'agent_nope'"):
            await test_call_service.place_platform_agent_call(
                db_session, tenant_id, "agent_nope", "+491701234567"
            )

    mock_adapter.create_outbound_call.assert_not_awaited()


@pytest.mark.asyncio
async def test_place_platform_agent_call_requires_from_number(db_session, tenant_id):
    with patch("backend.services.test_call_service.settings") as mock_settings:
        mock_settings.retell_from_number = ""
        with pytest.raises(test_call_service.TestCallError, match="RETELL_FROM_NUMBER"):
            await test_call_service.place_platform_agent_call(
                db_session, tenant_id, "agent_ext_9", "+491701234567"
            )


@pytest.mark.asyncio
async def test_create_outbound_call_record_rejects_ambiguous_agent(db_session, tenant_id):
    """Neither agent id makes the row unattributable; both makes "which agent ran this"
    ambiguous for every reader downstream. Both are programming errors, not user input.
    """
    with pytest.raises(ValueError, match="exactly one of"):
        await call_service.create_outbound_call_record(
            db_session, tenant_id, None, "call_x", "+491701234567"
        )

    import uuid as _uuid

    with pytest.raises(ValueError, match="exactly one of"):
        await call_service.create_outbound_call_record(
            db_session,
            tenant_id,
            _uuid.uuid4(),
            "call_y",
            "+491701234567",
            external_agent_id="agent_ext_9",
        )


# --- dynamic variables: personalizing an agent whose prompt we don't own -------


def _platform_adapter(declared: list[str]) -> AsyncMock:
    adapter = AsyncMock()
    adapter.list_platform_agents.return_value = [
        {"external_id": "agent_ext_9", "name": "Roofing Agent Test Case #1"}
    ]
    adapter.get_agent_dynamic_variables.return_value = declared
    adapter.create_outbound_call.return_value = "call_ext_9"
    return adapter


@pytest.mark.asyncio
async def test_platform_call_sends_declared_variables(db_session, tenant_id):
    adapter = _platform_adapter(["company_name", "contact_name"])

    with (
        patch("backend.services.test_call_service.settings") as mock_settings,
        patch("backend.services.test_call_service.get_adapter", return_value=adapter),
    ):
        mock_settings.retell_from_number = "+15551234567"
        await test_call_service.place_platform_agent_call(
            db_session,
            tenant_id,
            "agent_ext_9",
            "+491701234567",
            dynamic_variables={"company_name": "Bristol Dental", "contact_name": "Maria"},
        )

    assert adapter.create_outbound_call.await_args.kwargs["dynamic_variables"] == {
        "company_name": "Bristol Dental",
        "contact_name": "Maria",
    }


@pytest.mark.asyncio
async def test_platform_call_refuses_to_dial_with_an_unfilled_placeholder(db_session, tenant_id):
    """Retell leaves an unsupplied {{placeholder}} literal in the prompt and the agent
    reads it aloud. Blocking beats spending a real call on that."""
    adapter = _platform_adapter(["company_name", "contact_name"])

    with (
        patch("backend.services.test_call_service.settings") as mock_settings,
        patch("backend.services.test_call_service.get_adapter", return_value=adapter),
    ):
        mock_settings.retell_from_number = "+15551234567"
        with pytest.raises(test_call_service.TestCallError, match="contact_name"):
            await test_call_service.place_platform_agent_call(
                db_session,
                tenant_id,
                "agent_ext_9",
                "+491701234567",
                dynamic_variables={"company_name": "Bristol Dental"},
            )

    adapter.create_outbound_call.assert_not_awaited()


@pytest.mark.asyncio
async def test_platform_call_treats_a_blank_value_as_missing(db_session, tenant_id):
    """A whitespace-only box is exactly as bad as an empty one — the placeholder still
    goes unfilled — so it must not sneak past the guard as "present"."""
    adapter = _platform_adapter(["company_name"])

    with (
        patch("backend.services.test_call_service.settings") as mock_settings,
        patch("backend.services.test_call_service.get_adapter", return_value=adapter),
    ):
        mock_settings.retell_from_number = "+15551234567"
        with pytest.raises(test_call_service.TestCallError, match="company_name"):
            await test_call_service.place_platform_agent_call(
                db_session,
                tenant_id,
                "agent_ext_9",
                "+491701234567",
                dynamic_variables={"company_name": "   "},
            )

    adapter.create_outbound_call.assert_not_awaited()


@pytest.mark.asyncio
async def test_platform_call_drops_variables_the_prompt_never_asked_for(db_session, tenant_id):
    """Harmless to Retell, but it would make the audit trail read as though the agent
    used data it never saw."""
    adapter = _platform_adapter(["company_name"])

    with (
        patch("backend.services.test_call_service.settings") as mock_settings,
        patch("backend.services.test_call_service.get_adapter", return_value=adapter),
    ):
        mock_settings.retell_from_number = "+15551234567"
        await test_call_service.place_platform_agent_call(
            db_session,
            tenant_id,
            "agent_ext_9",
            "+491701234567",
            dynamic_variables={"company_name": "Bristol Dental", "secret_note": "ignore me"},
        )

    assert adapter.create_outbound_call.await_args.kwargs["dynamic_variables"] == {
        "company_name": "Bristol Dental"
    }
