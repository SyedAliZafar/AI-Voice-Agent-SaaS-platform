"""DeepSeek API integration — the conversation brain.

ADR-003: tool execution happens server-side, here. The LLM decides WHAT to
call; execute_tool_calls actually runs it against our backend, giving us
full audit logging and guardrails before/after every tool invocation.
"""

import json
from typing import Any

from openai import AsyncOpenAI

from backend.config import get_settings
from backend.tools import get_tool_definitions, get_tool_handler

settings = get_settings()
client = AsyncOpenAI(api_key=settings.deepseek_api_key, base_url="https://api.deepseek.com")

MODEL = "deepseek-chat"
MAX_TOKENS = 1024


def _to_openai_tools() -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool["description"],
                "parameters": tool["input_schema"],
            },
        }
        for tool in get_tool_definitions()
    ]


async def get_agent_response(
    system_prompt: str,
    conversation_history: list[dict[str, str]],
    caller_context: dict[str, Any],
) -> str:
    """Send the conversation to DeepSeek, execute any tool calls, return final text.

    conversation_history: [{"role": "user"|"assistant", "content": "..."}]
    caller_context: {caller_number, tenant_id, agent_id, ...} — used for
    building tool-execution context, not sent verbatim to the LLM.
    """
    tools = _to_openai_tools()
    messages = [{"role": "system", "content": system_prompt}, *conversation_history]

    response = await client.chat.completions.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        messages=messages,
        tools=tools,
    )
    choice = response.choices[0]

    # Loop while DeepSeek wants to call tools, feeding results back until
    # it produces a final text response.
    while choice.finish_reason == "tool_calls":
        messages.append(choice.message)
        tool_results = await _execute_tool_calls(choice.message.tool_calls, caller_context)
        messages.extend(tool_results)

        response = await client.chat.completions.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            messages=messages,
            tools=tools,
        )
        choice = response.choices[0]

    return choice.message.content or "I'm sorry, I didn't catch that. Could you repeat it?"


async def complete_json(system_prompt: str, user_prompt: str, max_tokens: int = 1024) -> dict:
    """One-shot structured-output helper for non-conversational DeepSeek calls
    (e.g. research_service distilling a company brief). Reuses the same client/model
    as the call-time brain — no second DeepSeek client, no tools, no history.
    """
    response = await client.chat.completions.create(
        model=MODEL,
        max_tokens=max_tokens,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        response_format={"type": "json_object"},
    )
    content = response.choices[0].message.content or "{}"
    return json.loads(content)


async def _execute_tool_calls(tool_calls: list, caller_context: dict[str, Any]) -> list[dict]:
    results = []
    for tool_call in tool_calls:
        handler = get_tool_handler(tool_call.function.name)
        try:
            tool_input = json.loads(tool_call.function.arguments)
            result = await handler(tool_input, caller_context)
        except Exception as exc:  # noqa: BLE001 — log and surface to LLM, don't crash the call
            result = {"error": str(exc)}

        results.append(
            {
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": str(result),
            }
        )
    return results
