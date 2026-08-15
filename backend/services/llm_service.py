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

import asyncio
import json
import logging
import random
import time
from collections.abc import AsyncIterator, Callable, Coroutine
from functools import lru_cache
from typing import Any

from openai import AsyncOpenAI, BadRequestError

from backend.config import get_settings
from backend.tools import get_tool_definitions, get_tool_handler

logger = logging.getLogger(__name__)

settings = get_settings()

MAX_TOKENS = 1024

# Ceiling on a single provider's warm-up request (see warm_up_providers). Generous:
# the point is to bound a hung connection, not to race a slow-but-working one.
WARMUP_TIMEOUT_SECONDS = 10.0

# How long a tool-call round may run before the caller hears a filler phrase instead of
# silence (phase4.md Session 7). A Cal.com/HubSpot round-trip is the case this exists
# for; anything resolving faster than this never triggers a filler, so quick answers
# still feel immediate.
TOOL_CALL_FILLER_DELAY_SECONDS = 0.3
# Plain text, not audio: CONTEXT.md's "what NOT to build" rules out custom TTS, and
# retell_ws.py's frames carry a `content` string that Retell's own voice synthesizes.
# "Pre-recorded" here means pre-written and picked in-process — no LLM call, no
# synthesis on our side, so a filler costs no latency of its own.
_FILLER_PHRASES = (
    "Let me check on that for you...",
    "One moment...",
    "Just a second while I look that up...",
)


def _pick_filler_phrase() -> str:
    """Its own function so tests can patch it for a deterministic phrase."""
    return random.choice(_FILLER_PHRASES)


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
            f"Model provider '{provider}' has no API key configured (settings.{key_attr} is empty)"
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


async def warm_up_providers() -> dict[str, bool]:
    """Open a connection to every configured provider so the FIRST real call doesn't
    pay DNS + TLS on the caller's time. Called from main.py's lifespan.

    Measured 2026-08-15, first streamed completion's time-to-first-token:

        provider   cold     after this warm-up
        openai     2.76s    0.63s
        deepseek   0.98s    0.62s

    That ~2.1s OpenAI penalty is not hypothetical — it is what a real call spent as
    dead air on its greeting, long enough that the callee said "Hello?" over it and
    Retell cancelled the half-spoken turn (ADR-009 barge-in) and restarted it. The
    module docstring above already noted phase0.md measuring the same ~2.5s cold cost;
    this is the fix for it rather than another note about it.

    models.list() rather than a one-token completion: it costs no tokens, and it opens
    the very connection get_client() will hand to the first real turn — the @lru_cache
    on _client_for_provider is what carries the warmth across.

    Warms only providers with a key configured, so this stays correct as an
    OpenAI-or-DeepSeek deployment rather than assuming both.

    Never raises. A provider unreachable at boot must not stop the app from starting,
    and the cost of failing here is only that the first call pays what it pays today.
    Returns provider -> whether it warmed, for logging and for tests.
    """
    results: dict[str, bool] = {}
    for provider, configured in provider_configured_status().items():
        if not configured:
            continue
        try:
            client = _client_for_provider(provider)
            await asyncio.wait_for(client.models.list(), timeout=WARMUP_TIMEOUT_SECONDS)
            results[provider] = True
        except Exception:
            # Includes TimeoutError and LLMConfigError. Warn, don't propagate.
            logger.warning(
                "llm warm-up failed; first call to this provider will be slower",
                extra={"provider": provider},
                exc_info=True,
            )
            results[provider] = False
    return results


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


def _record_llm_timing(
    llm_events: list[dict[str, Any]] | None,
    *,
    stage: str,
    model: str,
    started_at: float,
    response: Any,
) -> None:
    """Append one timing/usage sample for a single completions.create() call.
    No-op when llm_events is None — callers that don't care about the baseline
    (tests, sandbox) don't pay for this or change behavior. usage is None for
    some providers/mock responses, hence the getattr guards."""
    if llm_events is None:
        return
    usage = getattr(response, "usage", None)
    llm_events.append(
        {
            "stage": stage,
            "model": model,
            "duration_ms": round((time.perf_counter() - started_at) * 1000, 2),
            "prompt_tokens": getattr(usage, "prompt_tokens", None),
            "completion_tokens": getattr(usage, "completion_tokens", None),
        }
    )


def _record_stream_timing(
    llm_events: list[dict[str, Any]] | None,
    *,
    stage: str,
    model: str,
    started_at: float,
    first_token_at: float | None,
    usage: Any,
) -> None:
    """Streaming counterpart to _record_llm_timing — same {stage, model, duration_ms,
    prompt_tokens, completion_tokens} shape (so CallEvent(event_type="llm_timing") rows
    and call_service.record_llm_events need no schema change), plus two additive keys:
    ttfb_ms (time to the first content delta — the metric streaming exists to improve;
    duration_ms is the full round-trip and should stay roughly flat) and streamed=True
    (so before/after rows are distinguishable in the same table). See CONTEXT.md ADR-009.
    """
    if llm_events is None:
        return
    now = time.perf_counter()
    llm_events.append(
        {
            "stage": stage,
            "model": model,
            "duration_ms": round((now - started_at) * 1000, 2),
            "ttfb_ms": round((first_token_at - started_at) * 1000, 2)
            if first_token_at is not None
            else None,
            "prompt_tokens": getattr(usage, "prompt_tokens", None),
            "completion_tokens": getattr(usage, "completion_tokens", None),
            "streamed": True,
        }
    )


# Per-provider memory of whether stream_options={"include_usage": True} is accepted.
# Both OpenAI and DeepSeek support it, but an OpenAI-compatible endpoint we haven't
# tested might 400 on it — see _create_stream. Starts optimistic (True == "try it").
_provider_stream_options_ok: dict[str, bool] = {}


async def _create_stream(
    client: AsyncOpenAI, *, model: str, messages: list, tool_kwargs: dict
) -> Any:
    """chat.completions.create(stream=True) with a one-time-per-provider fallback if
    stream_options isn't accepted. Without this guard, an unsupported provider would 400
    on every single turn and every one of those turns would surface as the caller-facing
    error fallback line — a degraded call for what's meant to be a metrics-only addition.
    """
    provider = provider_for(model)
    use_stream_options = _provider_stream_options_ok.get(provider, True)
    kwargs: dict[str, Any] = dict(
        model=model, max_tokens=MAX_TOKENS, messages=messages, stream=True, **tool_kwargs
    )
    if use_stream_options:
        kwargs["stream_options"] = {"include_usage": True}
    try:
        return await client.chat.completions.create(**kwargs)
    except BadRequestError:
        if not use_stream_options:
            raise
        _provider_stream_options_ok[provider] = False
        kwargs.pop("stream_options", None)
        return await client.chat.completions.create(**kwargs)


def _normalize_tool_calls(sdk_tool_calls: list) -> list[dict[str, Any]]:
    """Maps the non-streaming SDK's ChatCompletionMessageToolCall objects to the same
    {"id", "name", "arguments"} dict shape stream_agent_response accumulates from
    fragmented deltas — the one shape _execute_tool_calls and _run_tool_calls_shielded
    both take, so the tool-execution/shielding/event-sink logic is shared by both
    paths."""
    return [
        {"id": tc.id, "name": tc.function.name, "arguments": tc.function.arguments}
        for tc in sdk_tool_calls
    ]


def _default_spawn_tracked(coro: Coroutine) -> "asyncio.Task":
    """Fallback used when a caller (sandbox, scripts/check_custom_llm.py, tests) doesn't
    pass its own spawn_tracked — a plain untracked task. retell_ws.py always passes its
    own, which registers the task in a per-connection set so it survives a barge-in
    cancellation and gets drained on disconnect (ADR-009)."""
    return asyncio.create_task(coro)


def _start_tool_calls_shielded(
    tool_calls: list[dict[str, Any]],
    caller_context: dict[str, Any],
    on_tool_event: Callable[[dict[str, Any]], None] | None,
    spawn_tracked: Callable[[Coroutine], "asyncio.Task"],
    check_duplicate: Callable[[str, dict[str, Any]], dict[str, Any] | None] | None = None,
) -> "asyncio.Future[list[dict]]":
    """Starts _execute_tool_calls on a tracked, shielded task without awaiting it.

    Split out from _run_tool_calls_shielded so stream_agent_response can *race* the
    result against a timeout (the Session 7 filler) rather than only await it. The
    shield has to wrap the same future the caller awaits, or a barge-in landing during
    the filler wait would reach the real tool task — which is the exact thing ADR-009
    exists to prevent.
    """
    task = spawn_tracked(
        _execute_tool_calls(tool_calls, caller_context, on_tool_event, check_duplicate)
    )
    return asyncio.shield(task)


async def _run_tool_calls_shielded(
    tool_calls: list[dict[str, Any]],
    caller_context: dict[str, Any],
    on_tool_event: Callable[[dict[str, Any]], None] | None,
    spawn_tracked: Callable[[Coroutine], "asyncio.Task"],
    check_duplicate: Callable[[str, dict[str, Any]], dict[str, Any] | None] | None = None,
) -> list[dict]:
    """Runs _execute_tool_calls on a tracked task and shields the await.

    Barge-in cancellation (retell_ws.py cancelling a generation task on a new
    response_id) must interrupt speech, never an in-flight side effect — a caller
    hanging up mid-book_appointment must not leave Cal.com with a half-sent request and
    us with no record of it (ADR-009). asyncio.shield(coro) alone isn't enough: it gives
    no handle on the inner task, so completion becomes unobservable and a failure only
    surfaces as an unretrieved-exception warning. Creating the task explicitly via
    spawn_tracked gives both the shield and the reference, and registers it in the
    caller's per-connection pending-task set so it's drained on disconnect too.

    check_duplicate: see _execute_tool_calls — threaded through unchanged.
    """
    return await _start_tool_calls_shielded(
        tool_calls, caller_context, on_tool_event, spawn_tracked, check_duplicate
    )


async def get_agent_response(
    system_prompt: str,
    conversation_history: list[dict[str, str]],
    caller_context: dict[str, Any],
    *,
    model: str | None = None,
    tools_enabled: bool = True,
    llm_events: list[dict[str, Any]] | None = None,
    on_tool_event: Callable[[dict[str, Any]], None] | None = None,
    spawn_tracked: Callable[[Coroutine], "asyncio.Task"] | None = None,
    check_duplicate: Callable[[str, dict[str, Any]], dict[str, Any] | None] | None = None,
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
    llm_events: optional list the caller provides to collect a per-call timing/usage
    sample (stage, model, duration_ms, prompt_tokens, completion_tokens) for the
    initial call and, if the LLM calls a tool, each follow-up call. Baseline
    instrumentation ahead of the streaming-architecture work — see CONTEXT.md.
    on_tool_event / spawn_tracked / check_duplicate: optional, additive — see
    stream_agent_response and _run_tool_calls_shielded/_execute_tool_calls. None of the
    existing non-retell_ws callers (sandbox_service, scripts/check_custom_llm.py) pass
    these, so this function's behavior for them is unchanged; retell_ws.py passes all
    three on the kill-switch-off path so a barge-in — and a repeat request for an
    already-completed side effect — get the same handling as the streaming path
    (ADR-009).
    """
    model = model or settings.default_llm_model
    client = get_client(model)
    spawn_tracked = spawn_tracked or _default_spawn_tracked
    # The SDK's `tools` param isn't Optional (Iterable | Omit, not Iterable | None |
    # Omit) — passing tools=None would serialize as a literal "tools": null in the
    # request body instead of being omitted. Build kwargs conditionally so
    # tools_enabled=False genuinely omits the field.
    tool_kwargs = {"tools": _to_openai_tools()} if tools_enabled else {}
    messages = [{"role": "system", "content": system_prompt}, *conversation_history]

    started_at = time.perf_counter()
    response = await client.chat.completions.create(
        model=model,
        max_tokens=MAX_TOKENS,
        messages=messages,
        **tool_kwargs,
    )
    _record_llm_timing(
        llm_events, stage="initial", model=model, started_at=started_at, response=response
    )
    choice = response.choices[0]

    # Loop while the LLM wants to call tools, feeding results back until
    # it produces a final text response.
    while choice.finish_reason == "tool_calls":
        messages.append(choice.message)
        normalized = _normalize_tool_calls(choice.message.tool_calls)
        tool_results = await _run_tool_calls_shielded(
            normalized, caller_context, on_tool_event, spawn_tracked, check_duplicate
        )
        messages.extend(tool_results)

        started_at = time.perf_counter()
        response = await client.chat.completions.create(
            model=model,
            max_tokens=MAX_TOKENS,
            messages=messages,
            **tool_kwargs,
        )
        _record_llm_timing(
            llm_events, stage="tool_followup", model=model, started_at=started_at, response=response
        )
        choice = response.choices[0]

    return choice.message.content or "I'm sorry, I didn't catch that. Could you repeat it?"


async def stream_agent_response(
    system_prompt: str,
    conversation_history: list[dict[str, str]],
    caller_context: dict[str, Any],
    *,
    model: str | None = None,
    tools_enabled: bool = True,
    llm_events: list[dict[str, Any]] | None = None,
    on_tool_event: Callable[[dict[str, Any]], None] | None = None,
    spawn_tracked: Callable[[Coroutine], "asyncio.Task"] | None = None,
    check_duplicate: Callable[[str, dict[str, Any]], dict[str, Any] | None] | None = None,
) -> AsyncIterator[str]:
    """Streaming counterpart to get_agent_response (ADR-009) — same parameters, yields
    text deltas as they arrive instead of returning the whole reply at once. A deliberate
    separate function rather than a stream=True branch inside get_agent_response: that
    function has three other callers (sandbox_service.chat, scripts/check_custom_llm.py,
    and retell_ws.py's own kill-switch-off path) that must keep today's exact blocking
    behavior, and duplicating the tool-call loop here is a smaller risk than threading a
    stream flag through it.

    Yields "" -> never; on an empty completion (no content, no tool calls) yields the
    same "I'm sorry, I didn't catch that..." fallback get_agent_response returns, so both
    paths behave identically on that edge case.

    on_tool_event: see _execute_tool_calls — invoked synchronously, twice per tool call
    ("dispatched" before the handler runs, "result"/"error" after), so a side-effecting
    tool call leaves a durable trace even if this generator is later cancelled.
    spawn_tracked: see _run_tool_calls_shielded — registers the tool-execution task in
    the caller's per-connection pending-task set so a barge-in cancellation interrupts
    speech, never an in-flight side effect, and so disconnect can drain it to completion.
    retell_ws.py always passes its own; callers that don't care about cancellation
    (currently none, but tests exercise this) get an untracked asyncio.create_task.
    check_duplicate: see _execute_tool_calls — lets the caller intercept a repeat request
    for something already completed this call and short-circuit it instead of dispatching
    again (outliers.md §1 / phase4.md Session 8, server-enforced confirmation gating).
    """
    model = model or settings.default_llm_model
    client = get_client(model)
    spawn_tracked = spawn_tracked or _default_spawn_tracked
    tool_kwargs = {"tools": _to_openai_tools()} if tools_enabled else {}
    messages: list[Any] = [{"role": "system", "content": system_prompt}, *conversation_history]

    any_content = False
    stage = "initial"

    while True:
        started_at = time.perf_counter()
        first_token_at: float | None = None
        content_parts: list[str] = []
        tool_call_acc: dict[int, dict[str, str]] = {}
        finish_reason: str | None = None
        usage: Any = None

        stream = await _create_stream(
            client, model=model, messages=messages, tool_kwargs=tool_kwargs
        )
        async for chunk in stream:
            # The include_usage trailer chunk (see _create_stream) carries usage but an
            # EMPTY choices list — read usage first, then guard, or it's silently missed.
            if getattr(chunk, "usage", None):
                usage = chunk.usage
            if not chunk.choices:
                continue
            choice = chunk.choices[0]
            delta = choice.delta
            if delta.content:
                if first_token_at is None:
                    first_token_at = time.perf_counter()
                content_parts.append(delta.content)
                any_content = True
                yield delta.content
            if delta.tool_calls:
                # Fragmented across chunks: id/name usually arrive once, arguments in
                # pieces — accumulate by index, not by id (id may be empty on later
                # fragments of the same call).
                for tc in delta.tool_calls:
                    entry = tool_call_acc.setdefault(
                        tc.index, {"id": "", "name": "", "arguments": ""}
                    )
                    if tc.id:
                        entry["id"] = tc.id
                    if tc.function is not None and tc.function.name:
                        entry["name"] = tc.function.name
                    if tc.function is not None and tc.function.arguments:
                        entry["arguments"] += tc.function.arguments
            if choice.finish_reason:
                finish_reason = choice.finish_reason

        _record_stream_timing(
            llm_events,
            stage=stage,
            model=model,
            started_at=started_at,
            first_token_at=first_token_at,
            usage=usage,
        )

        if finish_reason != "tool_calls":
            break

        normalized = [tool_call_acc[i] for i in sorted(tool_call_acc)]
        messages.append(
            {
                "role": "assistant",
                "content": "".join(content_parts) or None,
                "tool_calls": [
                    {
                        "id": tc["id"],
                        "type": "function",
                        "function": {"name": tc["name"], "arguments": tc["arguments"]},
                    }
                    for tc in normalized
                ],
            }
        )
        # Race the tool round against a short timeout so a slow Cal.com/HubSpot
        # round-trip doesn't leave the caller in silence (phase4.md Session 7). The
        # filler is yielded like any other delta, so it reaches Retell through the
        # existing content-frame path with no protocol change. Awaiting `shielded`
        # afterwards is correct either way — an already-resolved future returns
        # immediately — and keeps the barge-in shield covering the real tool task
        # during the wait.
        shielded = _start_tool_calls_shielded(
            normalized, caller_context, on_tool_event, spawn_tracked, check_duplicate
        )
        done, _pending = await asyncio.wait({shielded}, timeout=TOOL_CALL_FILLER_DELAY_SECONDS)
        if not done:
            any_content = True
            yield _pick_filler_phrase()
        tool_results = await shielded
        messages.extend(tool_results)
        stage = "tool_followup"

    if not any_content:
        yield "I'm sorry, I didn't catch that. Could you repeat it?"


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


async def _execute_tool_calls(
    tool_calls: list[dict[str, Any]],
    caller_context: dict[str, Any],
    on_tool_event: Callable[[dict[str, Any]], None] | None = None,
    check_duplicate: Callable[[str, dict[str, Any]], dict[str, Any] | None] | None = None,
) -> list[dict]:
    """tool_calls: normalized {"id", "name", "arguments"} dicts — see _normalize_tool_calls
    for how the non-streaming SDK response's tool_calls map to this shape, and
    stream_agent_response for how streaming deltas accumulate directly into it. Kept
    dict-shaped (not the SDK's ChatCompletionMessageToolCall objects) so this one function
    serves both paths.

    on_tool_event, if given, fires synchronously (never awaited — see ADR-009) twice per
    tool call: once with phase="dispatched" right before the handler runs, once with
    phase="result"/"error" after. This is what lets a side-effecting tool call (e.g.
    book_appointment's Cal.com POST) leave a durable trace even if the surrounding
    generation is cancelled by a barge-in before this function returns — retell_ws.py's
    sink writes each event as a CallEvent(event_type="tool_call") row.

    check_duplicate, if given, is consulted BEFORE dispatch for every tool call —
    signature (tool_name, parsed_arguments) -> synthetic_result | None. A non-None return
    means "don't call the real handler; use this instead" and the tool_call_id gets that
    synthetic result fed back to the LLM as its "tool" message, with phase="dispatched"
    never firing (nothing was actually dispatched). This is retell_ws.py's server-enforced
    ledger check (ADR-009 §4c / phase4.md Session 8) — a real double-booking on
    2026-08-05 (outliers.md §1) showed the ledger's system-prompt note alone doesn't
    reliably stop a model from re-attempting a side effect it already completed; this is
    the code-level backstop that doesn't depend on the model choosing to comply.

    Runs in two phases (phase4.md Session 6) rather than one interleaved loop, so
    parallel dispatch can't turn the duplicate check into a race: phase 1 walks
    tool_calls synchronously — no `await` anywhere in it — parsing each call's
    arguments once and, for every call, running check_duplicate (if given) against
    completed_tool_calls as it stands at the start of this turn, before any of this
    batch's calls have dispatched. Because that whole pass never suspends, every
    check_duplicate call in it is guaranteed to see the same start-of-turn snapshot,
    not a sibling result that raced ahead — two tool calls in one turn can't race past
    the duplicate check together. Calls that clear the check move to phase 2, dispatched
    concurrently via asyncio.gather; each keeps firing its own dispatched (in phase 1)
    and result/error (at the end of its own coroutine) in that order, so per-tool_call_id
    event ordering holds regardless of gather's scheduling — it only depends on each
    coroutine's own statements running in program order. Called by both
    get_agent_response and stream_agent_response only via _run_tool_calls_shielded,
    which is what protects an in-flight call here from being abandoned mid-flight.
    """

    async def _dispatch(
        name: str,
        tool_call_id: str,
        parsed_arguments: Any,
        parse_error: Exception | None,
    ) -> dict:
        started_at = time.perf_counter()
        try:
            handler = get_tool_handler(name)
            if parse_error is not None:
                raise parse_error
            result = await handler(parsed_arguments, caller_context)
        except Exception as exc:  # noqa: BLE001 — log and surface to LLM, don't crash the call
            if on_tool_event:
                on_tool_event(
                    {
                        "phase": "error",
                        "tool": name,
                        "tool_call_id": tool_call_id,
                        "duration_ms": round((time.perf_counter() - started_at) * 1000, 2),
                        "error": str(exc),
                    }
                )
            return {
                "role": "tool",
                "tool_call_id": tool_call_id,
                "content": str({"error": str(exc)}),
            }
        else:
            if on_tool_event:
                on_tool_event(
                    {
                        "phase": "result",
                        "tool": name,
                        "tool_call_id": tool_call_id,
                        "duration_ms": round((time.perf_counter() - started_at) * 1000, 2),
                        "result": result,
                    }
                )
            return {"role": "tool", "tool_call_id": tool_call_id, "content": str(result)}

    # Phase 1 — synchronous, no `await`: parse once, check duplicates against the
    # ledger snapshot as it stands at the start of this turn, fire "skipped_duplicate"
    # or "dispatched" now. Nothing here can interleave with a sibling call's dispatch.
    results_by_id: dict[str, dict] = {}
    to_dispatch: list[tuple[str, str, Any, Exception | None]] = []
    for tool_call in tool_calls:
        name = tool_call["name"]
        tool_call_id = tool_call["id"]
        raw_arguments = tool_call["arguments"]

        try:
            parsed_arguments: Any = json.loads(raw_arguments)
            parse_error: Exception | None = None
        except (TypeError, ValueError) as exc:
            parsed_arguments = None
            parse_error = exc

        duplicate_result = None
        if check_duplicate is not None and parse_error is None:
            duplicate_result = check_duplicate(name, parsed_arguments)

        if duplicate_result is not None:
            if on_tool_event:
                on_tool_event(
                    {
                        "phase": "skipped_duplicate",
                        "tool": name,
                        "tool_call_id": tool_call_id,
                        "arguments": raw_arguments,
                        "result": duplicate_result,
                    }
                )
            results_by_id[tool_call_id] = {
                "role": "tool",
                "tool_call_id": tool_call_id,
                "content": str(duplicate_result),
            }
            continue

        if on_tool_event:
            on_tool_event(
                {
                    "phase": "dispatched",
                    "tool": name,
                    "tool_call_id": tool_call_id,
                    "arguments": raw_arguments,
                }
            )
        to_dispatch.append((name, tool_call_id, parsed_arguments, parse_error))

    # Phase 2 — concurrent dispatch of everything that cleared the duplicate check.
    if to_dispatch:
        dispatched_results = await asyncio.gather(
            *(
                _dispatch(name, tool_call_id, parsed_arguments, parse_error)
                for name, tool_call_id, parsed_arguments, parse_error in to_dispatch
            )
        )
        for (_, tool_call_id, _, _), result in zip(to_dispatch, dispatched_results, strict=True):
            results_by_id[tool_call_id] = result

    return [results_by_id[tool_call["id"]] for tool_call in tool_calls]
