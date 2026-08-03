"""LLM provider integration — the conversation brain.

ADR-003: tool execution happens server-side, here. The LLM decides WHAT to
call; execute_tool_calls actually runs it against our backend, giving us
full audit logging and guardrails before/after every tool invocation.

ADR-008: DeepSeek and OpenAI both speak the OpenAI-compatible chat-completions
protocol, so "which provider" reduces to api_key + base_url + model — no separate
SDKs, no per-provider branching in the call-time logic below. A model id resolves
to a provider via MODEL_CATALOG (or a prefix guess for an id we haven't listed),
and each provider gets exactly one cached AsyncOpenAI client (see get_client) —
phase0.md measured ~2.5s of dead air on a cold client (DNS + TLS), so constructing
one per call/turn is not an option.
"""

import json
from functools import lru_cache
from typing import Any

from openai import AsyncOpenAI

from backend.config import get_settings
from backend.tools import get_tool_definitions, get_tool_handler

settings = get_settings()

MAX_TOKENS = 1024


class LLMConfigError(Exception):
    """A model id doesn't resolve to a known provider, or that provider's API key
    is unset. Distinct from a runtime OpenAI/DeepSeek API error — this is a
    configuration problem callers can act on (fix .env, pick another model)."""


# provider name -> (base_url, settings attribute holding its API key).
# base_url=None means "use the openai SDK's own default" (api.openai.com).
_PROVIDERS: dict[str, tuple[str | None, str]] = {
    "deepseek": ("https://api.deepseek.com", "deepseek_api_key"),
    "openai": (None, "openai_api_key"),
}

# The models selectable per-agent (frontend's model dropdown reads this via
# GET /api/agents/models). Not exhaustive — provider_for falls back to prefix
# inference for anything not listed here, so a new model id works immediately,
# but this is what shows up as a first-class choice in the UI.
MODEL_CATALOG: list[dict[str, str]] = [
    {"id": "deepseek-chat", "label": "DeepSeek Chat", "provider": "deepseek"},
    {"id": "deepseek-reasoner", "label": "DeepSeek Reasoner", "provider": "deepseek"},
    {"id": "gpt-4o-mini", "label": "GPT-4o mini", "provider": "openai"},
    {"id": "gpt-4o", "label": "GPT-4o", "provider": "openai"},
    {"id": "gpt-4.1-mini", "label": "GPT-4.1 mini", "provider": "openai"},
    {"id": "gpt-4.1", "label": "GPT-4.1", "provider": "openai"},
    {"id": "gpt-5.6-luna", "label": "GPT-5.6 Luna", "provider": "openai"},
]

_CATALOG_PROVIDER_BY_ID = {m["id"]: m["provider"] for m in MODEL_CATALOG}


def provider_for(model: str) -> str:
    """Resolve a model id to a provider name. Catalog lookup first, then a prefix
    guess so an unlisted-but-valid model id (e.g. a new GPT release) still works
    without a code change. Raises LLMConfigError if neither resolves."""
    provider = _CATALOG_PROVIDER_BY_ID.get(model)
    if provider:
        return provider

    if model.startswith("gpt-") or model.startswith("o1") or model.startswith("o3"):
        return "openai"
    if model.startswith("deepseek-"):
        return "deepseek"

    raise LLMConfigError(f"Unknown model '{model}' — no provider could be inferred for it")


@lru_cache
def _client_for_provider(provider: str) -> AsyncOpenAI:
    base_url, key_attr = _PROVIDERS[provider]
    api_key = getattr(settings, key_attr)
    if not api_key:
        raise LLMConfigError(
            f"Model provider '{provider}' has no API key configured "
            f"(settings.{key_attr} is empty)"
        )
    kwargs: dict[str, Any] = {"api_key": api_key}
    if base_url:
        kwargs["base_url"] = base_url
    return AsyncOpenAI(**kwargs)


def get_client(model: str) -> AsyncOpenAI:
    """Resolve a model id to its provider's client. Cached per provider (see
    _client_for_provider) — never construct a fresh AsyncOpenAI per call."""
    return _client_for_provider(provider_for(model))


def provider_configured_status() -> dict[str, bool]:
    """Which providers currently have an API key set — GET /api/agents/models uses
    this to grey out models whose provider isn't configured yet."""
    return {
        provider: bool(getattr(settings, key_attr))
        for provider, (_, key_attr) in _PROVIDERS.items()
    }


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
    *,
    model: str | None = None,
    tools_enabled: bool = True,
) -> str:
    """Send the conversation to the configured LLM, execute any tool calls, return
    final text.

    conversation_history: [{"role": "user"|"assistant", "content": "..."}]
    caller_context: {caller_number, tenant_id, agent_id, ...} — used for
    building tool-execution context, not sent verbatim to the LLM.
    model: model id, e.g. "deepseek-chat" or "gpt-4o-mini". Defaults to
    settings.default_llm_model.
    tools_enabled: False sends no tool definitions at all and skips the
    tool-call loop entirely — used by the sandbox so a text chat can't
    accidentally hit real integrations (book_appointment, create_lead, ...).
    """
    model = model or settings.default_llm_model
    client = get_client(model)
    # The SDK's `tools` param isn't Optional (Iterable | Omit, not Iterable | None |
    # Omit) — passing tools=None would serialize as a literal "tools": null in the
    # request body instead of being omitted. Build kwargs conditionally so
    # tools_enabled=False genuinely omits the field.
    tool_kwargs = {"tools": _to_openai_tools()} if tools_enabled else {}
    messages = [{"role": "system", "content": system_prompt}, *conversation_history]

    response = await client.chat.completions.create(
        model=model,
        max_tokens=MAX_TOKENS,
        messages=messages,
        **tool_kwargs,
    )
    choice = response.choices[0]

    # Loop while the LLM wants to call tools, feeding results back until
    # it produces a final text response.
    while choice.finish_reason == "tool_calls":
        messages.append(choice.message)
        tool_results = await _execute_tool_calls(choice.message.tool_calls, caller_context)
        messages.extend(tool_results)

        response = await client.chat.completions.create(
            model=model,
            max_tokens=MAX_TOKENS,
            messages=messages,
            **tool_kwargs,
        )
        choice = response.choices[0]

    return choice.message.content or "I'm sorry, I didn't catch that. Could you repeat it?"


async def complete_json(
    system_prompt: str, user_prompt: str, max_tokens: int = 1024, *, model: str | None = None
) -> dict:
    """One-shot structured-output helper for non-conversational calls (e.g.
    research_service distilling a company brief). No tools, no history. Stays on
    the global default model — callers here have no per-agent notion.
    """
    model = model or settings.default_llm_model
    client = get_client(model)
    response = await client.chat.completions.create(
        model=model,
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
