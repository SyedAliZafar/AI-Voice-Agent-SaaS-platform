"""Tests for the LLM tool-calling loop and provider abstraction in llm_service
(ADR-008).

Mocks the AsyncOpenAI client entirely — these tests verify our orchestration logic
(the tool-call loop, fallback text, provider/model resolution), not any real LLM's
output.
"""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from openai import BadRequestError

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


@pytest.fixture(autouse=True)
def _clear_stream_options_memory():
    """_create_stream remembers per-provider whether stream_options was accepted
    (ADR-009) — a fallback learned in one test must not leak into the next."""
    llm_service._provider_stream_options_ok.clear()
    yield
    llm_service._provider_stream_options_ok.clear()


class _FakeStream:
    """Minimal stand-in for the async-iterable AsyncOpenAI returns for
    stream=True — `await client.chat.completions.create(...)` resolves to this,
    then `async for chunk in stream`."""

    def __init__(self, chunks: list):
        self._chunks = chunks

    def __aiter__(self):
        return self._gen()

    async def _gen(self):
        for chunk in self._chunks:
            yield chunk


def _stream_chunk(
    content: str | None = None,
    tool_calls: list | None = None,
    finish_reason: str | None = None,
    usage: object | None = None,
):
    """One ChatCompletionChunk-shaped stand-in. SimpleNamespace rather than MagicMock —
    MagicMock(name=...) hijacks the mock's own repr name instead of setting a `.name`
    attribute, which is exactly the attribute a tool-call delta's `.function.name` needs."""
    delta = SimpleNamespace(content=content, tool_calls=tool_calls)
    choice = SimpleNamespace(delta=delta, finish_reason=finish_reason)
    return SimpleNamespace(choices=[choice], usage=usage)


def _usage_trailer_chunk(usage: object):
    """The include_usage trailer chunk: usage set, choices EMPTY — see
    stream_agent_response's guard for why usage must be read before that empty-choices
    check, not after."""
    return SimpleNamespace(choices=[], usage=usage)


def _tc_delta(
    index: int,
    id: str | None = None,
    name: str | None = None,
    arguments: str | None = None,
):
    return SimpleNamespace(
        index=index, id=id, function=SimpleNamespace(name=name, arguments=arguments)
    )


def _bad_request_error() -> BadRequestError:
    request = httpx.Request("POST", "https://example.com/chat/completions")
    response = httpx.Response(400, request=request, json={"error": "stream_options unsupported"})
    return BadRequestError("stream_options not supported", response=response, body=None)


async def _collect(agen):
    return [chunk async for chunk in agen]


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


class TestStreamAgentResponse:
    """stream_agent_response (ADR-009) — the streaming counterpart to
    get_agent_response. Deliberately a separate function (see its docstring), so these
    tests don't touch get_agent_response's own behavior/tests above."""

    @pytest.mark.asyncio
    async def test_deltas_yield_in_order_and_join_to_full_text(self, mock_client):
        mock_client.chat.completions.create.return_value = _FakeStream(
            [
                _stream_chunk(content="Sure"),
                _stream_chunk(content=", I"),
                _stream_chunk(content=" can help."),
                _stream_chunk(finish_reason="stop"),
            ]
        )

        chunks = await _collect(
            llm_service.stream_agent_response(
                system_prompt="You are helpful.",
                conversation_history=[{"role": "user", "content": "Hi"}],
                caller_context={},
            )
        )

        assert chunks == ["Sure", ", I", " can help."]
        assert "".join(chunks) == "Sure, I can help."

    @pytest.mark.asyncio
    async def test_tool_call_round_trip_with_fragmented_deltas(self, mock_client):
        # First round: id+name arrive in the first fragment, arguments split across two
        # more — exactly how OpenAI/DeepSeek stream a tool call.
        first_round = _FakeStream(
            [
                _stream_chunk(
                    tool_calls=[_tc_delta(0, id="tu_1", name="transfer_call", arguments="")]
                ),
                _stream_chunk(tool_calls=[_tc_delta(0, arguments='{"reason": ')]),
                _stream_chunk(tool_calls=[_tc_delta(0, arguments='"caller asked"}')]),
                _stream_chunk(finish_reason="tool_calls"),
            ]
        )
        second_round = _FakeStream(
            [
                _stream_chunk(content="Transferring you now."),
                _stream_chunk(finish_reason="stop"),
            ]
        )
        mock_client.chat.completions.create.side_effect = [first_round, second_round]

        handler = AsyncMock(return_value={"transferred": True})
        with patch.object(llm_service, "get_tool_handler", return_value=handler):
            chunks = await _collect(
                llm_service.stream_agent_response(
                    system_prompt="You are helpful.",
                    conversation_history=[{"role": "user", "content": "I want a human"}],
                    caller_context={},
                )
            )

        assert "".join(chunks) == "Transferring you now."
        handler.assert_awaited_once_with({"reason": "caller asked"}, {})
        # The second round's request must carry the assistant tool-call message and the
        # tool's result — proof the accumulated fragments were correctly assembled.
        second_call_kwargs = mock_client.chat.completions.create.call_args_list[1].kwargs
        second_call_messages = second_call_kwargs["messages"]
        assistant_msg = next(m for m in second_call_messages if m.get("role") == "assistant")
        assert assistant_msg["tool_calls"][0]["function"]["name"] == "transfer_call"
        expected_args = '{"reason": "caller asked"}'
        assert assistant_msg["tool_calls"][0]["function"]["arguments"] == expected_args
        tool_msg = next(m for m in second_call_messages if m.get("role") == "tool")
        assert tool_msg["tool_call_id"] == "tu_1"

    @staticmethod
    def _tool_call_rounds():
        """The two streams a one-tool-call turn needs: a round that finishes with
        tool_calls, then the follow-up round that speaks the answer."""
        first_round = _FakeStream(
            [
                _stream_chunk(
                    tool_calls=[_tc_delta(0, id="tu_1", name="check_availability", arguments="{}")]
                ),
                _stream_chunk(finish_reason="tool_calls"),
            ]
        )
        second_round = _FakeStream(
            [
                _stream_chunk(content="Yes, that slot is free."),
                _stream_chunk(finish_reason="stop"),
            ]
        )
        return first_round, second_round

    @pytest.mark.asyncio
    async def test_slow_tool_call_yields_a_filler_before_the_answer(self, mock_client):
        """phase4.md Session 7: a tool round slower than the threshold must put a spoken
        filler on the wire so the caller isn't sitting in silence during a Cal.com/HubSpot
        round-trip. The filler is yielded like any other delta — that's what carries it
        through retell_ws.py's existing content-frame path."""
        mock_client.chat.completions.create.side_effect = self._tool_call_rounds()

        async def slow_handler(_input, _ctx):
            await asyncio.sleep(0.05)
            return {"available": True}

        with (
            patch.object(llm_service, "get_tool_handler", return_value=slow_handler),
            patch.object(llm_service, "TOOL_CALL_FILLER_DELAY_SECONDS", 0.01),
            patch.object(llm_service, "_pick_filler_phrase", return_value="One moment..."),
        ):
            chunks = await _collect(
                llm_service.stream_agent_response(
                    system_prompt="You are helpful.",
                    conversation_history=[{"role": "user", "content": "is 4pm free?"}],
                    caller_context={},
                )
            )

        # Filler first, real answer after — order matters, it's what the caller hears.
        assert chunks == ["One moment...", "Yes, that slot is free."]

    @pytest.mark.asyncio
    async def test_fast_tool_call_yields_no_filler(self, mock_client):
        """A tool call that resolves inside the threshold must stay silent — a quick
        answer should feel immediate, not be padded with an unnecessary phrase."""
        mock_client.chat.completions.create.side_effect = self._tool_call_rounds()

        handler = AsyncMock(return_value={"available": True})
        with (
            patch.object(llm_service, "get_tool_handler", return_value=handler),
            patch.object(llm_service, "TOOL_CALL_FILLER_DELAY_SECONDS", 5.0),
            patch.object(llm_service, "_pick_filler_phrase", return_value="One moment..."),
        ):
            chunks = await _collect(
                llm_service.stream_agent_response(
                    system_prompt="You are helpful.",
                    conversation_history=[{"role": "user", "content": "is 4pm free?"}],
                    caller_context={},
                )
            )

        assert chunks == ["Yes, that slot is free."]

    @pytest.mark.asyncio
    async def test_filler_wait_still_shields_the_tool_call_from_barge_in(self, mock_client):
        """ADR-009: the filler race must not weaken the barge-in shield. Cancelling the
        generation while it's parked in the filler wait has to stop the speech but let
        the in-flight tool call run to completion."""
        mock_client.chat.completions.create.side_effect = self._tool_call_rounds()
        completed = {"flag": False}
        pending: set = set()

        def spawn_tracked(coro):
            task = asyncio.create_task(coro)
            pending.add(task)
            task.add_done_callback(pending.discard)
            return task

        async def slow_handler(_input, _ctx):
            await asyncio.sleep(0.05)
            completed["flag"] = True
            return {"available": True}

        with (
            patch.object(llm_service, "get_tool_handler", return_value=slow_handler),
            patch.object(llm_service, "TOOL_CALL_FILLER_DELAY_SECONDS", 0.01),
        ):
            stream = llm_service.stream_agent_response(
                system_prompt="You are helpful.",
                conversation_history=[{"role": "user", "content": "is 4pm free?"}],
                caller_context={},
                spawn_tracked=spawn_tracked,
            )
            consumer = asyncio.create_task(_collect(stream))
            await asyncio.sleep(0.02)  # let the tool dispatch and the filler wait elapse
            consumer.cancel()
            with pytest.raises(asyncio.CancelledError):
                await consumer

            assert pending  # the shielded tool task outlived the cancelled generation
            await asyncio.gather(*pending)

        assert completed["flag"] is True

    @pytest.mark.asyncio
    async def test_empty_completion_yields_fallback(self, mock_client):
        mock_client.chat.completions.create.return_value = _FakeStream(
            [_stream_chunk(content=None, finish_reason="stop")]
        )

        chunks = await _collect(
            llm_service.stream_agent_response(
                system_prompt="You are helpful.",
                conversation_history=[{"role": "user", "content": "..."}],
                caller_context={},
            )
        )

        assert len(chunks) == 1
        assert "sorry" in chunks[0].lower()

    @pytest.mark.asyncio
    async def test_llm_events_get_ttfb_and_streamed_flag_with_matching_stage_values(
        self, mock_client
    ):
        usage = SimpleNamespace(prompt_tokens=10, completion_tokens=3)
        mock_client.chat.completions.create.return_value = _FakeStream(
            [
                _stream_chunk(content="Hi"),
                _stream_chunk(finish_reason="stop"),
                _usage_trailer_chunk(usage),
            ]
        )

        llm_events: list[dict] = []
        await _collect(
            llm_service.stream_agent_response(
                system_prompt="You are helpful.",
                conversation_history=[{"role": "user", "content": "Hi"}],
                caller_context={},
                llm_events=llm_events,
            )
        )

        assert len(llm_events) == 1
        event = llm_events[0]
        # Same stage/model/duration_ms/prompt_tokens/completion_tokens shape
        # call_service.record_llm_events already persists — no schema change.
        assert event["stage"] == "initial"
        assert event["prompt_tokens"] == 10
        assert event["completion_tokens"] == 3
        assert event["duration_ms"] >= 0
        # Additive keys.
        assert event["streamed"] is True
        assert event["ttfb_ms"] is not None and event["ttfb_ms"] >= 0

    @pytest.mark.asyncio
    async def test_bad_request_on_stream_options_retries_once_without_it(self, mock_client):
        mock_client.chat.completions.create.side_effect = [
            _bad_request_error(),
            _FakeStream([_stream_chunk(content="ok"), _stream_chunk(finish_reason="stop")]),
        ]

        chunks = await _collect(
            llm_service.stream_agent_response(
                system_prompt="You are helpful.",
                conversation_history=[{"role": "user", "content": "Hi"}],
                caller_context={},
                model="deepseek-chat",
            )
        )

        assert "".join(chunks) == "ok"
        assert mock_client.chat.completions.create.call_count == 2
        first_kwargs = mock_client.chat.completions.create.call_args_list[0].kwargs
        second_kwargs = mock_client.chat.completions.create.call_args_list[1].kwargs
        assert "stream_options" in first_kwargs
        assert "stream_options" not in second_kwargs
        # Remembered per-provider — a later call for the same provider shouldn't retry.
        assert llm_service._provider_stream_options_ok["deepseek"] is False


class TestToolCallShielding:
    """_run_tool_calls_shielded / _execute_tool_calls's on_tool_event sink — the barge-in
    safety net (ADR-009 §4a/§4b): cancellation must interrupt speech, never abandon an
    in-flight tool call, and a dispatch-time trace must exist even if the turn never
    reaches a result."""

    @staticmethod
    def _tracking_spawner(pending: set):
        def spawn_tracked(coro):
            task = asyncio.create_task(coro)
            pending.add(task)
            task.add_done_callback(pending.discard)
            return task

        return spawn_tracked

    @pytest.mark.asyncio
    async def test_execute_tool_calls_emits_dispatched_then_result(self):
        events: list[dict] = []
        handler = AsyncMock(return_value={"booked": True, "confirmation_id": "abc123"})
        with patch.object(llm_service, "get_tool_handler", return_value=handler):
            results = await llm_service._execute_tool_calls(
                [{"id": "tc1", "name": "book_appointment", "arguments": '{"a": 1}'}],
                {},
                on_tool_event=events.append,
            )

        assert [e["phase"] for e in events] == ["dispatched", "result"]
        assert events[0]["arguments"] == '{"a": 1}'
        assert events[1]["result"] == {"booked": True, "confirmation_id": "abc123"}
        assert results[0]["tool_call_id"] == "tc1"

    @pytest.mark.asyncio
    async def test_cancelled_error_is_not_converted_to_a_tool_error(self):
        async def cancelling_handler(_input, _ctx):
            raise asyncio.CancelledError()

        with patch.object(llm_service, "get_tool_handler", return_value=cancelling_handler):
            with pytest.raises(asyncio.CancelledError):
                await llm_service._execute_tool_calls(
                    [{"id": "tc1", "name": "book_appointment", "arguments": "{}"}], {}
                )

    @pytest.mark.asyncio
    async def test_shielded_tool_survives_outer_cancellation(self):
        completed = {"flag": False}

        async def slow_handler(_input, _ctx):
            await asyncio.sleep(0.05)
            completed["flag"] = True
            return {"booked": True}

        pending: set = set()
        spawn_tracked = self._tracking_spawner(pending)

        with patch.object(llm_service, "get_tool_handler", return_value=slow_handler):
            outer = asyncio.create_task(
                llm_service._run_tool_calls_shielded(
                    [{"id": "tc1", "name": "book_appointment", "arguments": "{}"}],
                    {},
                    None,
                    spawn_tracked,
                )
            )
            await asyncio.sleep(0.01)  # let the handler start
            outer.cancel()
            with pytest.raises(asyncio.CancelledError):
                await outer

            # The outer await raised, but the inner task must still be alive and tracked
            # so the caller (retell_ws.py's drain loop) can let it finish.
            assert pending
            await asyncio.gather(*pending)

        assert completed["flag"] is True

    @pytest.mark.asyncio
    async def test_dispatch_event_recorded_even_when_cancelled_before_result(self):
        events: list[dict] = []

        async def slow_handler(_input, _ctx):
            await asyncio.sleep(0.05)
            return {"booked": True}

        pending: set = set()
        spawn_tracked = self._tracking_spawner(pending)

        with patch.object(llm_service, "get_tool_handler", return_value=slow_handler):
            outer = asyncio.create_task(
                llm_service._run_tool_calls_shielded(
                    [{"id": "tc1", "name": "book_appointment", "arguments": "{}"}],
                    {},
                    events.append,
                    spawn_tracked,
                )
            )
            await asyncio.sleep(0.01)
            outer.cancel()
            with pytest.raises(asyncio.CancelledError):
                await outer

            # "dispatched" survives the cancellation even though "result" hasn't
            # happened yet — this is the row that proves the call was made at all.
            assert [e["phase"] for e in events] == ["dispatched"]
            await asyncio.gather(*pending)

        assert [e["phase"] for e in events] == ["dispatched", "result"]


class TestCheckDuplicate:
    """_execute_tool_calls's check_duplicate hook (ADR-009 §4c server-enforced half /
    phase4.md Session 8) — the code-level backstop added after a real double-booking
    (outliers.md §1) showed the ledger's system-prompt note alone doesn't reliably stop
    a model from re-attempting something it already completed."""

    @pytest.mark.asyncio
    async def test_duplicate_match_skips_the_real_handler(self):
        handler = AsyncMock(return_value={"booked": True, "confirmation_id": "should-not-happen"})
        synthetic = {"already_completed": True, "reference": "abc123"}

        def check_duplicate(tool, arguments):
            assert tool == "book_appointment"
            assert arguments == {"start_time": "2026-08-06T16:00:00", "attendee_email": "a@b.com"}
            return synthetic

        raw_arguments = json.dumps(
            {"start_time": "2026-08-06T16:00:00", "attendee_email": "a@b.com"}
        )
        with patch.object(llm_service, "get_tool_handler", return_value=handler):
            results = await llm_service._execute_tool_calls(
                [{"id": "tc1", "name": "book_appointment", "arguments": raw_arguments}],
                {},
                check_duplicate=check_duplicate,
            )

        handler.assert_not_awaited()
        assert results == [{"role": "tool", "tool_call_id": "tc1", "content": str(synthetic)}]

    @pytest.mark.asyncio
    async def test_duplicate_match_emits_skipped_duplicate_not_dispatched(self):
        events: list[dict] = []
        handler = AsyncMock(return_value={"booked": True})

        with patch.object(llm_service, "get_tool_handler", return_value=handler):
            await llm_service._execute_tool_calls(
                [{"id": "tc1", "name": "book_appointment", "arguments": "{}"}],
                {},
                on_tool_event=events.append,
                check_duplicate=lambda tool, args: {"already_completed": True},
            )

        # No "dispatched" — nothing was actually dispatched to the real handler.
        assert [e["phase"] for e in events] == ["skipped_duplicate"]
        assert events[0]["tool"] == "book_appointment"
        assert events[0]["tool_call_id"] == "tc1"
        assert events[0]["result"] == {"already_completed": True}

    @pytest.mark.asyncio
    async def test_no_match_proceeds_normally(self):
        handler = AsyncMock(return_value={"booked": True, "confirmation_id": "xyz"})

        with patch.object(llm_service, "get_tool_handler", return_value=handler):
            results = await llm_service._execute_tool_calls(
                [{"id": "tc1", "name": "book_appointment", "arguments": '{"a": 1}'}],
                {},
                check_duplicate=lambda tool, args: None,
            )

        handler.assert_awaited_once()
        assert results[0]["content"] == str({"booked": True, "confirmation_id": "xyz"})

    @pytest.mark.asyncio
    async def test_no_check_duplicate_callback_is_unaffected(self):
        """Default (check_duplicate=None) — every existing caller (get_agent_response
        without the kwarg, sandbox_service, scripts/check_custom_llm.py) must see zero
        behavior change."""
        handler = AsyncMock(return_value={"ok": True})
        with patch.object(llm_service, "get_tool_handler", return_value=handler):
            results = await llm_service._execute_tool_calls(
                [{"id": "tc1", "name": "book_appointment", "arguments": "{}"}], {}
            )
        handler.assert_awaited_once()
        assert results[0]["content"] == str({"ok": True})

    @pytest.mark.asyncio
    async def test_unparseable_arguments_are_not_treated_as_duplicate(self):
        """check_duplicate needs parsed arguments to compare against — malformed JSON
        must fall through to the normal handler path (which will itself fail on the
        same malformed JSON, exactly as it did before check_duplicate existed) rather
        than being silently swallowed by the duplicate check."""
        check_duplicate = MagicMock(return_value=None)
        handler = AsyncMock()

        with patch.object(llm_service, "get_tool_handler", return_value=handler):
            results = await llm_service._execute_tool_calls(
                [{"id": "tc1", "name": "book_appointment", "arguments": "not json"}],
                {},
                check_duplicate=check_duplicate,
            )

        check_duplicate.assert_not_called()
        handler.assert_not_awaited()
        assert "error" in results[0]["content"]

    @pytest.mark.asyncio
    async def test_check_duplicate_threaded_through_get_agent_response(self, mock_client):
        """End-to-end through the public entry point, not just _execute_tool_calls
        directly — proves the kwarg actually reaches the tool-calling loop."""
        tool_call = MagicMock(id="tc1")
        tool_call.function.name = "book_appointment"
        tool_call.function.arguments = '{"start_time": "x", "attendee_email": "a@b.com"}'
        tool_call_response = _completion("tool_calls", tool_calls=[tool_call])
        final_response = _completion("stop", content="Already booked that for you.")
        mock_client.chat.completions.create.side_effect = [tool_call_response, final_response]

        handler = AsyncMock(return_value={"booked": True})
        synthetic = {"already_completed": True, "instruction": "tell the caller"}

        with patch.object(llm_service, "get_tool_handler", return_value=handler):
            result = await llm_service.get_agent_response(
                system_prompt="You are helpful.",
                conversation_history=[{"role": "user", "content": "book it again"}],
                caller_context={},
                check_duplicate=lambda tool, args: synthetic,
            )

        handler.assert_not_awaited()
        assert result == "Already booked that for you."
        second_call_messages = mock_client.chat.completions.create.call_args_list[1].kwargs[
            "messages"
        ]
        tool_msg = next(m for m in second_call_messages if m.get("role") == "tool")
        assert tool_msg["content"] == str(synthetic)


class TestConcurrentToolDispatch:
    """phase4.md Session 6: multiple tool calls in one turn now dispatch via
    asyncio.gather instead of a sequential for loop. These cover the properties a
    single-tool-call test can't: that dispatch is actually concurrent, that the
    duplicate check for a whole batch is evaluated against one start-of-turn ledger
    snapshot rather than racing sibling results, and that on_tool_event stays
    correctly ordered per tool_call_id when writes happen concurrently."""

    @pytest.mark.asyncio
    async def test_two_tool_calls_dispatch_concurrently(self):
        async def slow_handler(_input, _ctx):
            await asyncio.sleep(0.05)
            return {"ok": True}

        with patch.object(llm_service, "get_tool_handler", return_value=slow_handler):
            started = asyncio.get_event_loop().time()
            await llm_service._execute_tool_calls(
                [
                    {"id": "tc1", "name": "book_appointment", "arguments": "{}"},
                    {"id": "tc2", "name": "book_appointment", "arguments": "{}"},
                ],
                {},
            )
            elapsed = asyncio.get_event_loop().time() - started

        # Sequential would take >=0.1s; concurrent should stay close to one sleep.
        assert elapsed < 0.09

    @pytest.mark.asyncio
    async def test_duplicate_check_sees_start_of_turn_snapshot_for_whole_batch(self):
        """Two calls in the same batch that would duplicate each other (not a
        pre-existing ledger entry) — check_duplicate is consulted for both before
        either dispatches, so both observe "not yet in the ledger" and both proceed,
        rather than one racing ahead of the other's check."""
        seen_args: list[dict] = []

        def check_duplicate(tool, arguments):
            seen_args.append(arguments)
            return None  # nothing in the ledger yet for either call

        handler = AsyncMock(return_value={"booked": True})
        with patch.object(llm_service, "get_tool_handler", return_value=handler):
            results = await llm_service._execute_tool_calls(
                [
                    {"id": "tc1", "name": "book_appointment", "arguments": '{"a": 1}'},
                    {"id": "tc2", "name": "book_appointment", "arguments": '{"a": 1}'},
                ],
                {},
                check_duplicate=check_duplicate,
            )

        # Both duplicate checks ran (synchronously, before any dispatch) and both
        # calls proceeded to the real handler.
        assert seen_args == [{"a": 1}, {"a": 1}]
        assert handler.await_count == 2
        assert {r["tool_call_id"] for r in results} == {"tc1", "tc2"}

    @pytest.mark.asyncio
    async def test_event_ordering_holds_per_tool_call_under_concurrency(self):
        """tc2's handler finishes before tc1's — dispatched must still precede
        result/error for each tool_call_id individually, even though completion
        order across calls is reversed."""
        events: list[dict] = []

        async def handler(input_, _ctx):
            if input_.get("which") == "tc1":
                await asyncio.sleep(0.05)
            return {"ok": True}

        with patch.object(llm_service, "get_tool_handler", return_value=handler):
            await llm_service._execute_tool_calls(
                [
                    {"id": "tc1", "name": "book_appointment", "arguments": '{"which": "tc1"}'},
                    {"id": "tc2", "name": "book_appointment", "arguments": '{"which": "tc2"}'},
                ],
                {},
                on_tool_event=events.append,
            )

        by_call: dict[str, list[str]] = {"tc1": [], "tc2": []}
        for event in events:
            by_call[event["tool_call_id"]].append(event["phase"])
        assert by_call["tc1"] == ["dispatched", "result"]
        assert by_call["tc2"] == ["dispatched", "result"]

    @pytest.mark.asyncio
    async def test_results_returned_in_original_tool_call_order(self):
        """tc2 resolves before tc1, but the returned list must still match the
        order tool_calls were given in, keyed by tool_call_id."""

        async def handler(input_, _ctx):
            if input_.get("which") == "tc1":
                await asyncio.sleep(0.05)
            return {"which": input_.get("which")}

        with patch.object(llm_service, "get_tool_handler", return_value=handler):
            results = await llm_service._execute_tool_calls(
                [
                    {"id": "tc1", "name": "book_appointment", "arguments": '{"which": "tc1"}'},
                    {"id": "tc2", "name": "book_appointment", "arguments": '{"which": "tc2"}'},
                ],
                {},
            )

        assert [r["tool_call_id"] for r in results] == ["tc1", "tc2"]
