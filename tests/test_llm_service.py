"""Tests for the DeepSeek tool-calling loop in llm_service.

Mocks the AsyncOpenAI (DeepSeek-compatible) client entirely — these tests verify
our orchestration logic (the tool-call loop, fallback text), not DeepSeek's
actual output.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.services import llm_service


def _completion(finish_reason: str, content: str | None = None, tool_calls: list | None = None):
    message = MagicMock(content=content, tool_calls=tool_calls)
    choice = MagicMock(finish_reason=finish_reason, message=message)
    return MagicMock(choices=[choice])


@pytest.mark.asyncio
async def test_get_agent_response_simple_text():
    mock_response = _completion("stop", content="Sure, I can help with that.")

    with patch.object(
        llm_service.client.chat.completions, "create", AsyncMock(return_value=mock_response)
    ):
        result = await llm_service.get_agent_response(
            system_prompt="You are helpful.",
            conversation_history=[{"role": "user", "content": "Hi"}],
            caller_context={},
        )

    assert result == "Sure, I can help with that."


@pytest.mark.asyncio
async def test_get_agent_response_executes_tool_then_responds():
    tool_call = MagicMock(id="tu_1")
    tool_call.function.name = "transfer_call"
    tool_call.function.arguments = json.dumps({"reason": "caller requested human"})

    tool_call_response = _completion("tool_calls", tool_calls=[tool_call])
    final_response = _completion("stop", content="Transferring you now.")

    with patch.object(
        llm_service.client.chat.completions,
        "create",
        AsyncMock(side_effect=[tool_call_response, final_response]),
    ):
        result = await llm_service.get_agent_response(
            system_prompt="You are helpful.",
            conversation_history=[{"role": "user", "content": "I want a human"}],
            caller_context={},
        )

    assert result == "Transferring you now."


@pytest.mark.asyncio
async def test_get_agent_response_falls_back_when_no_content():
    mock_response = _completion("stop", content=None)

    with patch.object(
        llm_service.client.chat.completions, "create", AsyncMock(return_value=mock_response)
    ):
        result = await llm_service.get_agent_response(
            system_prompt="You are helpful.",
            conversation_history=[{"role": "user", "content": "..."}],
            caller_context={},
        )

    assert "sorry" in result.lower()
