"""Tests for the LLM tool-calling loop and provider abstraction in llm_service
(ADR-008).

Mocks the AsyncOpenAI client entirely — these tests verify our orchestration logic
(the tool-call loop, fallback text, provider/model resolution), not any real LLM's
output.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.services import llm_service


def _completion(finish_reason: str, content: str | None = None, tool_calls: list | None = None):
    message = MagicMock(content=content, tool_calls=tool_calls)
    choice = MagicMock(finish_reason=finish_reason, message=message)
    return MagicMock(choices=[choice])


@pytest.fixture(autouse=True)
def _clear_client_cache():
    """get_client caches one AsyncOpenAI per provider (lru_cache) — a cached client
    from one test (or a real settings-backed client) would leak into the next."""
    llm_service._client_for_provider.cache_clear()
    yield
    llm_service._client_for_provider.cache_clear()


@pytest.fixture
def mock_client():
    """Patch get_client to always return the same mock, and let tests set its
    chat.completions.create behavior directly."""
    client = MagicMock()
    client.chat.completions.create = AsyncMock()
    with patch.object(llm_service, "get_client", return_value=client):
        yield client


@pytest.mark.asyncio
async def test_get_agent_response_simple_text(mock_client):
    mock_client.chat.completions.create.return_value = _completion(
        "stop", content="Sure, I can help with that."
    )

    result = await llm_service.get_agent_response(
        system_prompt="You are helpful.",
        conversation_history=[{"role": "user", "content": "Hi"}],
        caller_context={},
    )

    assert result == "Sure, I can help with that."


@pytest.mark.asyncio
async def test_get_agent_response_executes_tool_then_responds(mock_client):
    tool_call = MagicMock(id="tu_1")
    tool_call.function.name = "transfer_call"
    tool_call.function.arguments = json.dumps({"reason": "caller requested human"})

    tool_call_response = _completion("tool_calls", tool_calls=[tool_call])
    final_response = _completion("stop", content="Transferring you now.")
    mock_client.chat.completions.create.side_effect = [tool_call_response, final_response]

    result = await llm_service.get_agent_response(
        system_prompt="You are helpful.",
        conversation_history=[{"role": "user", "content": "I want a human"}],
        caller_context={},
    )

    assert result == "Transferring you now."


@pytest.mark.asyncio
async def test_get_agent_response_falls_back_when_no_content(mock_client):
    mock_client.chat.completions.create.return_value = _completion("stop", content=None)

    result = await llm_service.get_agent_response(
        system_prompt="You are helpful.",
        conversation_history=[{"role": "user", "content": "..."}],
        caller_context={},
    )

    assert "sorry" in result.lower()


@pytest.mark.asyncio
async def test_tools_enabled_false_omits_tools_kwarg(mock_client):
    mock_client.chat.completions.create.return_value = _completion("stop", content="ok")

    await llm_service.get_agent_response(
        system_prompt="You are helpful.",
        conversation_history=[{"role": "user", "content": "Hi"}],
        caller_context={},
        tools_enabled=False,
    )

    _, kwargs = mock_client.chat.completions.create.call_args
    assert "tools" not in kwargs


@pytest.mark.asyncio
async def test_tools_enabled_true_sends_tools_kwarg(mock_client):
    mock_client.chat.completions.create.return_value = _completion("stop", content="ok")

    await llm_service.get_agent_response(
        system_prompt="You are helpful.",
        conversation_history=[{"role": "user", "content": "Hi"}],
        caller_context={},
    )

    _, kwargs = mock_client.chat.completions.create.call_args
    assert kwargs["tools"] and len(kwargs["tools"]) > 0


class TestProviderResolution:
    def test_catalog_model_resolves_to_its_provider(self):
        assert llm_service.provider_for("deepseek-chat") == "deepseek"
        assert llm_service.provider_for("gpt-4o-mini") == "openai"

    def test_unlisted_model_falls_back_to_prefix_inference(self):
        assert llm_service.provider_for("gpt-5-nano") == "openai"
        assert llm_service.provider_for("deepseek-v99") == "deepseek"

    def test_unresolvable_model_raises_llm_config_error(self):
        with pytest.raises(llm_service.LLMConfigError):
            llm_service.provider_for("llama-3-70b")

    def test_missing_api_key_raises_llm_config_error(self):
        llm_service._client_for_provider.cache_clear()
        with patch.object(llm_service.settings, "openai_api_key", ""):
            with pytest.raises(llm_service.LLMConfigError):
                llm_service.get_client("gpt-4o-mini")

    def test_configured_provider_returns_a_client(self):
        llm_service._client_for_provider.cache_clear()
        with patch.object(llm_service.settings, "deepseek_api_key", "sk-test"):
            client = llm_service.get_client("deepseek-chat")
        assert client is not None

    def test_client_is_cached_per_provider(self):
        llm_service._client_for_provider.cache_clear()
        with patch.object(llm_service.settings, "deepseek_api_key", "sk-test"):
            first = llm_service.get_client("deepseek-chat")
            second = llm_service.get_client("deepseek-chat")
        assert first is second
