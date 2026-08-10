"""Tests for the Retell Custom LLM WebSocket handler (backend/api/retell_ws.py).

Deliberately does NOT use the `client`/`db_session` fixtures the rest of this suite
shares (tests/conftest.py). Those work by handing FastAPI's `Depends(get_db)` the exact
same already-open AsyncSession the test created — fine for httpx's ASGITransport, which
runs everything in the test's own event loop. But `retell_ws.py` intentionally never
uses `Depends(get_db)` (see its module docstring: sessions are opened fresh per
connection, not held for the socket's lifetime), and Starlette's `TestClient` drives
websockets from its own thread/event loop via an anyio portal — awaiting an AsyncSession
that was created in a *different* loop raises "Future attached to a different loop".

So instead: seed a temp file-backed SQLite DB synchronously via asyncio.run() (that
loop closes before the TestClient's portal starts — nothing async survives across the
boundary), then patch backend.api.retell_ws.AsyncSessionLocal to a NullPool-backed
sessionmaker for that file. NullPool means every session opens a fresh connection in
whatever loop is active when it's used, which is what makes this safe across threads.

ADR-009 (streaming + barge-in) note: llm_streaming_enabled defaults True, so
llm_websocket now calls llm_service.stream_agent_response — an async generator — not
get_agent_response, for every test below except the one that explicitly turns the kill
switch off. stream_agent_response is patched with a plain async-generator function
wrapped in a MagicMock (see _stream_returning/_stream_raising) rather than AsyncMock,
because calling an async generator function returns the generator object synchronously
— there's no coroutine to await at the call site itself, only at each `__anext__`.
"""

import asyncio
import json
import threading
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from backend.api.retell_ws import (
    _duplicate_tool_result,
    _find_duplicate_ledger_entry,
    _ledger_entry,
    _ledger_note,
    _to_conversation_history,
)
from backend.main import app
from backend.models.agent import Agent
from backend.models.base import Base
from backend.models.call import Call, CallEvent


def _seed_db(
    db_url: str,
    agent_id: uuid.UUID,
    tenant_id: uuid.UUID,
    call_external_id: str,
    system_prompt: str = "You are a helpful assistant.",
) -> None:
    async def _run() -> None:
        engine = create_async_engine(db_url, poolclass=NullPool)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session:
            session.add(
                Agent(
                    id=agent_id,
                    tenant_id=tenant_id,
                    name="Test Agent",
                    system_prompt=system_prompt,
                    platform="retell",
                    use_custom_llm=True,
                )
            )
            session.add(
                Call(
                    tenant_id=tenant_id,
                    agent_id=agent_id,
                    caller_number="+15551234567",
                    status="in_progress",
                    started_at=datetime.now(UTC),
                    external_id=call_external_id,
                )
            )
            await session.commit()
        await engine.dispose()

    asyncio.run(_run())


def _stream_returning(*texts: str):
    """A stream_agent_response replacement that yields each of `texts` as a separate
    delta, then completes — the streaming-mock equivalent of AsyncMock(return_value=...)
    for the old blocking get_agent_response."""

    async def _gen(*args, **kwargs):
        for t in texts:
            yield t

    return _gen


def _stream_raising(exc: BaseException):
    """A stream_agent_response replacement that raises `exc` before yielding anything —
    matching how a real LLMConfigError (get_client resolving a bad model) or SDK error
    surfaces on the very first delta, so the single-frame fallback wire behavior is
    unchanged from the pre-streaming tests."""

    async def _gen(*args, **kwargs):
        if False:
            yield ""  # pragma: no cover - unreachable; makes this an async generator fn
        raise exc

    return _gen


def _recv_until_complete(ws) -> list[dict]:
    frames = []
    while True:
        frame = ws.receive_json()
        frames.append(frame)
        if frame.get("content_complete"):
            break
    return frames


def test_to_conversation_history_maps_retell_roles():
    """Retell uses role "agent"; llm_service.get_agent_response expects "assistant"."""
    transcript = [
        {"role": "user", "content": "Hi there"},
        {"role": "agent", "content": "Hello, how can I help?"},
    ]
    assert _to_conversation_history(transcript) == [
        {"role": "user", "content": "Hi there"},
        {"role": "assistant", "content": "Hello, how can I help?"},
    ]


def test_llm_websocket_closes_unknown_call(tmp_path):
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'unknown.db'}"
    _seed_db(db_url, uuid.uuid4(), uuid.uuid4(), "some-other-call-id")

    test_engine = create_async_engine(db_url, poolclass=NullPool)
    test_session_factory = async_sessionmaker(test_engine, expire_on_commit=False)

    with patch("backend.api.retell_ws.AsyncSessionLocal", test_session_factory):
        with TestClient(app) as client:
            with client.websocket_connect("/llm-websocket/no-such-call") as ws:
                with pytest.raises(WebSocketDisconnect) as exc_info:
                    ws.receive_json()
                assert exc_info.value.code == 1008


def test_llm_websocket_ping_pong_and_streamed_response(tmp_path):
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'happy.db'}"
    tenant_id = uuid.uuid4()
    agent_id = uuid.uuid4()
    call_external_id = "call_abc123"
    _seed_db(db_url, agent_id, tenant_id, call_external_id, system_prompt="You are Ali.")

    test_engine = create_async_engine(db_url, poolclass=NullPool)
    test_session_factory = async_sessionmaker(test_engine, expire_on_commit=False)
    mock_stream = MagicMock(side_effect=_stream_returning("Hello there!"))

    with (
        patch("backend.api.retell_ws.AsyncSessionLocal", test_session_factory),
        patch("backend.services.llm_service.stream_agent_response", mock_stream),
        patch("backend.api.retell_ws.call_ws.publish_call_event", AsyncMock()),
    ):
        with TestClient(app) as client:
            with client.websocket_connect(f"/llm-websocket/{call_external_id}") as ws:
                config_msg = ws.receive_json()
                assert config_msg["response_type"] == "config"

                ws.send_json({"interaction_type": "ping_pong", "timestamp": 123})
                pong = ws.receive_json()
                assert pong == {"response_type": "ping_pong", "timestamp": 123}

                ws.send_json(
                    {
                        "interaction_type": "response_required",
                        "response_id": 7,
                        "transcript": [{"role": "user", "content": "Hi"}],
                    }
                )
                frames = _recv_until_complete(ws)

    # One partial delta frame, then one empty terminal frame — see retell_ws._generate.
    assert [f["response_id"] for f in frames] == [7, 7]
    assert [f["content_complete"] for f in frames] == [False, True]
    assert frames[0]["content"] == "Hello there!"
    assert frames[1]["content"] == ""
    assert frames[-1]["end_call"] is False

    mock_stream.assert_called_once()
    call_args = mock_stream.call_args
    # The agent's own prompt, plus the [CONTEXT] block _system_prompt_with_context
    # appends (current date, caller number) — see its docstring for why.
    assert call_args.args[0].startswith("You are Ali.")
    assert "[CONTEXT]" in call_args.args[0]
    assert call_args.args[1] == [{"role": "user", "content": "Hi"}]
    assert call_args.args[2]["agent_id"] == str(agent_id)
    assert call_args.args[2]["tenant_id"] == str(tenant_id)


def test_llm_websocket_kill_switch_off_uses_blocking_path(tmp_path):
    """settings.llm_streaming_enabled=False must restore the exact pre-streaming
    wire behavior: one frame, sent via get_agent_response, never stream_agent_response."""
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'kill_switch.db'}"
    tenant_id = uuid.uuid4()
    agent_id = uuid.uuid4()
    call_external_id = "call_kill_switch_1"
    _seed_db(db_url, agent_id, tenant_id, call_external_id, system_prompt="You are Ali.")

    test_engine = create_async_engine(db_url, poolclass=NullPool)
    test_session_factory = async_sessionmaker(test_engine, expire_on_commit=False)
    mock_get = AsyncMock(return_value="Hello there!")
    mock_stream = MagicMock(side_effect=_stream_returning("should not be used"))

    with (
        patch("backend.api.retell_ws.AsyncSessionLocal", test_session_factory),
        patch("backend.api.retell_ws.settings.llm_streaming_enabled", False),
        patch("backend.services.llm_service.get_agent_response", mock_get),
        patch("backend.services.llm_service.stream_agent_response", mock_stream),
        patch("backend.api.retell_ws.call_ws.publish_call_event", AsyncMock()),
    ):
        with TestClient(app) as client:
            with client.websocket_connect(f"/llm-websocket/{call_external_id}") as ws:
                ws.receive_json()  # config
                ws.send_json(
                    {
                        "interaction_type": "response_required",
                        "response_id": 1,
                        "transcript": [{"role": "user", "content": "Hi"}],
                    }
                )
                frames = _recv_until_complete(ws)

    assert len(frames) == 1
    assert frames[0]["content"] == "Hello there!"
    assert frames[0]["content_complete"] is True
    mock_get.assert_awaited_once()
    mock_stream.assert_not_called()


def test_llm_websocket_falls_back_on_llm_config_error(tmp_path):
    """An unresolvable model or missing provider key must not drop the socket — the
    call gets CONTEXT.md's documented fallback line instead."""
    from backend.services import llm_service

    db_url = f"sqlite+aiosqlite:///{tmp_path / 'config_error.db'}"
    tenant_id = uuid.uuid4()
    agent_id = uuid.uuid4()
    call_external_id = "call_config_error_1"
    _seed_db(db_url, agent_id, tenant_id, call_external_id, system_prompt="You are Ali.")

    test_engine = create_async_engine(db_url, poolclass=NullPool)
    test_session_factory = async_sessionmaker(test_engine, expire_on_commit=False)
    mock_stream = MagicMock(
        side_effect=_stream_raising(llm_service.LLMConfigError("no key configured"))
    )

    with (
        patch("backend.api.retell_ws.AsyncSessionLocal", test_session_factory),
        patch("backend.services.llm_service.stream_agent_response", mock_stream),
        patch("backend.api.retell_ws.call_ws.publish_call_event", AsyncMock()),
    ):
        with TestClient(app) as client:
            with client.websocket_connect(f"/llm-websocket/{call_external_id}") as ws:
                ws.receive_json()  # config
                ws.send_json(
                    {
                        "interaction_type": "response_required",
                        "response_id": 1,
                        "transcript": [{"role": "user", "content": "Hi"}],
                    }
                )
                frames = _recv_until_complete(ws)

    # No content ever streamed before the error — exactly one frame, same as before.
    assert len(frames) == 1
    assert frames[0]["content"] == "I'm having trouble, let me transfer you."
    assert frames[0]["content_complete"] is True


def test_llm_websocket_falls_back_on_unexpected_llm_error(tmp_path):
    """A timeout/rate-limit/5xx from the OpenAI-compatible SDK is not an LLMConfigError,
    but it must still fall back to a safe spoken message instead of killing the socket."""
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'unexpected_error.db'}"
    tenant_id = uuid.uuid4()
    agent_id = uuid.uuid4()
    call_external_id = "call_unexpected_error_1"
    _seed_db(db_url, agent_id, tenant_id, call_external_id, system_prompt="You are Ali.")

    test_engine = create_async_engine(db_url, poolclass=NullPool)
    test_session_factory = async_sessionmaker(test_engine, expire_on_commit=False)
    mock_stream = MagicMock(side_effect=_stream_raising(TimeoutError("upstream timed out")))

    with (
        patch("backend.api.retell_ws.AsyncSessionLocal", test_session_factory),
        patch("backend.services.llm_service.stream_agent_response", mock_stream),
        patch("backend.api.retell_ws.call_ws.publish_call_event", AsyncMock()),
    ):
        with TestClient(app) as client:
            with client.websocket_connect(f"/llm-websocket/{call_external_id}") as ws:
                ws.receive_json()  # config
                ws.send_json(
                    {
                        "interaction_type": "response_required",
                        "response_id": 1,
                        "transcript": [{"role": "user", "content": "Hi"}],
                    }
                )
                frames = _recv_until_complete(ws)
                assert len(frames) == 1
                assert (
                    frames[0]["content"]
                    == "I'm having some trouble, let me get someone to help you."
                )
                assert frames[0]["content_complete"] is True

                # The socket must still be alive for a second turn after the failure.
                ws.send_json({"interaction_type": "ping_pong", "timestamp": 1})
                pong = ws.receive_json()
                assert pong == {"response_type": "ping_pong", "timestamp": 1}


def test_llm_websocket_persists_turns_and_publishes(tmp_path):
    """The point of _persist_and_publish_turn: a live exchange gets written to
    Transcript.turns as it happens, and broadcast over ws.py's Redis channel — not
    just recorded after the fact via the post-call webhook."""
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'persist.db'}"
    tenant_id = uuid.uuid4()
    agent_id = uuid.uuid4()
    call_external_id = "call_persist_1"
    _seed_db(db_url, agent_id, tenant_id, call_external_id, system_prompt="You are Ali.")

    test_engine = create_async_engine(db_url, poolclass=NullPool)
    test_session_factory = async_sessionmaker(test_engine, expire_on_commit=False)
    mock_stream = MagicMock(side_effect=_stream_returning("Hello", " there!"))
    persisted = threading.Event()

    async def _mock_publish(*args, **kwargs):
        persisted.set()

    mock_publish = AsyncMock(side_effect=_mock_publish)

    with (
        patch("backend.api.retell_ws.AsyncSessionLocal", test_session_factory),
        patch("backend.services.llm_service.stream_agent_response", mock_stream),
        patch("backend.api.retell_ws.call_ws.publish_call_event", mock_publish),
    ):
        with TestClient(app) as client:
            with client.websocket_connect(f"/llm-websocket/{call_external_id}") as ws:
                ws.receive_json()  # config
                ws.send_json(
                    {
                        "interaction_type": "response_required",
                        "response_id": 1,
                        "transcript": [{"role": "user", "content": "Hi"}],
                    }
                )
                _recv_until_complete(ws)
                # _persist_and_publish_turn now runs on its own shielded, tracked task
                # (ADR-009) rather than inline in the receive loop, so a following
                # ping_pong round-trip no longer guarantees it has finished — wait on
                # publish_call_event (the last thing that function does) explicitly
                # instead of relying on message ordering. Also matters for the `with`
                # blocks below: Starlette's TestClient forcibly cancels the connection's
                # whole cancel scope shortly after close(), which would otherwise race
                # (and could cancel) this still-in-flight persistence.
                assert persisted.wait(timeout=5), "persist/publish never completed"
                ws.send_json({"interaction_type": "ping_pong", "timestamp": 1})
                ws.receive_json()  # pong

    async def _fetch_transcript():
        from backend.services import call_service

        async with test_session_factory() as session:
            call = await call_service.get_call_by_external_id(session, call_external_id)
            return await call_service.get_transcript(session, call.id, tenant_id)

    transcript = asyncio.run(_fetch_transcript())
    assert transcript is not None
    assert [t["role"] for t in transcript.turns] == ["caller", "agent"]
    assert transcript.turns[0]["text"] == "Hi"
    # Joined from both streamed deltas — the persisted text, unlike the wire frames,
    # is the concatenated whole.
    assert transcript.turns[1]["text"] == "Hello there!"

    mock_publish.assert_awaited_once()
    published_call_id, published_event = mock_publish.await_args.args
    assert published_call_id == call_external_id
    assert published_event["role"] == "agent"
    assert published_event["text"] == "Hello there!"


def test_llm_websocket_persist_failure_does_not_break_response(tmp_path):
    """A DB/Redis hiccup while persisting a turn must never take down a live call —
    the response frames Retell is waiting on have already been sent by the time this
    runs, and _persist_and_publish_turn swallows its own exceptions."""
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'persist_fail.db'}"
    tenant_id = uuid.uuid4()
    agent_id = uuid.uuid4()
    call_external_id = "call_persist_fail_1"
    _seed_db(db_url, agent_id, tenant_id, call_external_id, system_prompt="You are Ali.")

    test_engine = create_async_engine(db_url, poolclass=NullPool)
    test_session_factory = async_sessionmaker(test_engine, expire_on_commit=False)
    mock_stream = MagicMock(side_effect=_stream_returning("Hello there!"))

    with (
        patch("backend.api.retell_ws.AsyncSessionLocal", test_session_factory),
        patch("backend.services.llm_service.stream_agent_response", mock_stream),
        patch(
            "backend.api.retell_ws.call_service.record_turns",
            AsyncMock(side_effect=RuntimeError("db exploded")),
        ),
        patch("backend.api.retell_ws.call_ws.publish_call_event", AsyncMock()),
    ):
        with TestClient(app) as client:
            with client.websocket_connect(f"/llm-websocket/{call_external_id}") as ws:
                ws.receive_json()  # config
                ws.send_json(
                    {
                        "interaction_type": "response_required",
                        "response_id": 1,
                        "transcript": [{"role": "user", "content": "Hi"}],
                    }
                )
                frames = _recv_until_complete(ws)
                assert "".join(f["content"] for f in frames) == "Hello there!"

                # The socket must still be alive for a second turn after the failure.
                ws.send_json({"interaction_type": "ping_pong", "timestamp": 1})
                pong = ws.receive_json()
                assert pong == {"response_type": "ping_pong", "timestamp": 1}


def test_llm_websocket_barge_in_cancels_stale_generation(tmp_path):
    """ADR-009: a response_required with a NEW response_id while a turn is still
    generating cancels the stale task instead of letting it finish — the caller hears
    the new turn, not a lingering answer to the question they already talked over."""
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'barge_in.db'}"
    tenant_id = uuid.uuid4()
    agent_id = uuid.uuid4()
    call_external_id = "call_barge_in_1"
    _seed_db(db_url, agent_id, tenant_id, call_external_id, system_prompt="You are Ali.")

    test_engine = create_async_engine(db_url, poolclass=NullPool)
    test_session_factory = async_sessionmaker(test_engine, expire_on_commit=False)

    call_count = {"n": 0}
    cancelled = {"flag": False}

    async def fake_stream(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            try:
                yield "stale-chunk"
                # Never completes on its own (bounded so a broken cancellation path
                # fails the test in ~30s instead of hanging the suite forever).
                await asyncio.sleep(30)
            finally:
                cancelled["flag"] = True
        else:
            yield "fresh-response"

    with (
        patch("backend.api.retell_ws.AsyncSessionLocal", test_session_factory),
        patch("backend.services.llm_service.stream_agent_response", fake_stream),
        patch("backend.api.retell_ws.call_ws.publish_call_event", AsyncMock()),
    ):
        with TestClient(app) as client:
            with client.websocket_connect(f"/llm-websocket/{call_external_id}") as ws:
                ws.receive_json()  # config
                ws.send_json(
                    {
                        "interaction_type": "response_required",
                        "response_id": 1,
                        "transcript": [{"role": "user", "content": "tell me a long story"}],
                    }
                )
                first_frame = ws.receive_json()
                assert first_frame["response_id"] == 1
                assert first_frame["content"] == "stale-chunk"

                # Barge-in: a new turn arrives before the first one finished.
                ws.send_json(
                    {
                        "interaction_type": "response_required",
                        "response_id": 2,
                        "transcript": [
                            {"role": "user", "content": "tell me a long story"},
                            {"role": "user", "content": "actually never mind"},
                        ],
                    }
                )

                frames = _recv_until_complete(ws)

                # The receive loop awaits the cancelled task before starting the new
                # one (see llm_websocket), so by the time any response_id=2 frame is
                # observable, task 1's cancellation has already run to completion.
                assert cancelled["flag"] is True

                # Socket survives the barge-in.
                ws.send_json({"interaction_type": "ping_pong", "timestamp": 99})
                pong = ws.receive_json()
                assert pong == {"response_type": "ping_pong", "timestamp": 99}

    assert all(f["response_id"] == 2 for f in frames)
    assert "".join(f["content"] for f in frames) == "fresh-response"


def test_llm_websocket_ping_pong_answered_while_generating(tmp_path):
    """Direct proof the receive loop is no longer blocked on the LLM call — a ping_pong
    sent mid-generation must be answered before that generation finishes."""
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'keepalive.db'}"
    tenant_id = uuid.uuid4()
    agent_id = uuid.uuid4()
    call_external_id = "call_keepalive_1"
    _seed_db(db_url, agent_id, tenant_id, call_external_id, system_prompt="You are Ali.")

    test_engine = create_async_engine(db_url, poolclass=NullPool)
    test_session_factory = async_sessionmaker(test_engine, expire_on_commit=False)

    async def fake_stream(*args, **kwargs):
        yield "chunk"
        await asyncio.sleep(30)  # bounded — see barge-in test's comment
        yield "unreachable"

    with (
        patch("backend.api.retell_ws.AsyncSessionLocal", test_session_factory),
        patch("backend.services.llm_service.stream_agent_response", fake_stream),
        patch("backend.api.retell_ws.call_ws.publish_call_event", AsyncMock()),
    ):
        with TestClient(app) as client:
            with client.websocket_connect(f"/llm-websocket/{call_external_id}") as ws:
                ws.receive_json()  # config
                ws.send_json(
                    {
                        "interaction_type": "response_required",
                        "response_id": 1,
                        "transcript": [{"role": "user", "content": "Hi"}],
                    }
                )
                partial = ws.receive_json()
                assert partial["content"] == "chunk"

                ws.send_json({"interaction_type": "ping_pong", "timestamp": 42})
                pong = ws.receive_json()
                assert pong == {"response_type": "ping_pong", "timestamp": 42}


def test_llm_websocket_shielded_slow_tool_completes_and_is_recorded(tmp_path):
    """ADR-009 §4a/§4b: a tool call slower than the generation around it must not be
    abandoned — spawn_tracked's task keeps running after the generator yields more
    content, and its "dispatched"/"result" CallEvent(event_type="tool_call") rows get
    written via the fire-and-forget sink even though the turn that dispatched it has
    already moved on.

    Deliberately keeps the socket open throughout rather than exercising an actual
    disconnect: Starlette's TestClient tears a websocket connection down by forcibly
    cancelling the whole per-connection anyio cancel scope shortly after close() (see
    WebSocketTestSession.__exit__/_run) — under anyio's asyncio backend that cancels
    every task spawned within the scope, including ones asyncio.shield() is protecting,
    which makes "hang up mid-booking, then assert the DB row after teardown" fundamentally
    racy against this test harness even though a REAL client disconnect (no such forced
    cancel scope) would not do this. That real-disconnect case is covered by the plan's
    manual verification step instead; what's tested here — that a slow tool task
    genuinely outlives the frame that dispatched it and still gets recorded — is the
    actual mechanism and is fully deterministic.
    """
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'shielded_tool.db'}"
    tenant_id = uuid.uuid4()
    agent_id = uuid.uuid4()
    call_external_id = "call_shielded_tool_1"
    _seed_db(db_url, agent_id, tenant_id, call_external_id, system_prompt="You are Ali.")

    test_engine = create_async_engine(db_url, poolclass=NullPool)
    test_session_factory = async_sessionmaker(test_engine, expire_on_commit=False)

    from backend.services import call_service as call_service_module

    _real_record_tool_event = call_service_module.record_tool_event
    dispatched_written = threading.Event()
    result_written = threading.Event()

    async def _tracking_record_tool_event(db, call, event):
        await _real_record_tool_event(db, call, event)
        if event["phase"] == "dispatched":
            dispatched_written.set()
        elif event["phase"] == "result":
            result_written.set()

    async def fake_stream(*args, **kwargs):
        on_tool_event = kwargs["on_tool_event"]
        spawn_tracked = kwargs["spawn_tracked"]

        on_tool_event(
            {
                "phase": "dispatched",
                "tool": "book_appointment",
                "tool_call_id": "tc1",
                "arguments": json.dumps(
                    {"start_time": "2026-01-01T10:00:00", "attendee_email": "a@b.com"}
                ),
            }
        )

        async def _slow_result():
            await asyncio.sleep(0.2)
            on_tool_event(
                {
                    "phase": "result",
                    "tool": "book_appointment",
                    "tool_call_id": "tc1",
                    "duration_ms": 5,
                    "result": {"booked": True, "confirmation_id": "conf123"},
                }
            )

        spawn_tracked(_slow_result())
        # The generation itself finishes well before the 0.2s tool task does — proving
        # the tool task isn't tied to the generator's own lifetime.
        yield "Booking in progress..."
        yield "All set, anything else?"

    with (
        patch("backend.api.retell_ws.AsyncSessionLocal", test_session_factory),
        patch("backend.services.llm_service.stream_agent_response", fake_stream),
        patch(
            "backend.api.retell_ws.call_service.record_tool_event",
            _tracking_record_tool_event,
        ),
        patch("backend.api.retell_ws.call_ws.publish_call_event", AsyncMock()),
    ):
        with TestClient(app) as client:
            with client.websocket_connect(f"/llm-websocket/{call_external_id}") as ws:
                ws.receive_json()  # config
                ws.send_json(
                    {
                        "interaction_type": "response_required",
                        "response_id": 1,
                        "transcript": [{"role": "user", "content": "book it"}],
                    }
                )
                _recv_until_complete(ws)
                assert dispatched_written.wait(timeout=2), "dispatched event never persisted"
                assert result_written.wait(timeout=2), "result event never persisted"

    async def _fetch_tool_events():
        async with test_session_factory() as session:
            call = (
                await session.execute(select(Call).where(Call.external_id == call_external_id))
            ).scalar_one()
            rows = (
                (
                    await session.execute(
                        select(CallEvent)
                        .where(CallEvent.call_id == call.id, CallEvent.event_type == "tool_call")
                        .order_by(CallEvent.ts)
                    )
                )
                .scalars()
                .all()
            )
            return [row.payload for row in rows]

    events = asyncio.run(_fetch_tool_events())
    assert [e["phase"] for e in events] == ["dispatched", "result"]
    assert events[1]["result"]["confirmation_id"] == "conf123"


def test_llm_websocket_ledger_note_reaches_next_turn_after_barge_in(tmp_path):
    """ADR-009 §4c: once a tool call completes, the next turn's conversation_history
    must carry a note telling the model not to repeat it — the case that matters is
    exactly a barge-in mid-tool-call, where Retell's own transcript has no record the
    call happened. This test proves the note reaches the model's messages; it can't
    prove the model honors it (mocked LLM) — that half is manual verification (see the
    plan's step 3)."""
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'ledger.db'}"
    tenant_id = uuid.uuid4()
    agent_id = uuid.uuid4()
    call_external_id = "call_ledger_1"
    _seed_db(db_url, agent_id, tenant_id, call_external_id, system_prompt="You are Ali.")

    test_engine = create_async_engine(db_url, poolclass=NullPool)
    test_session_factory = async_sessionmaker(test_engine, expire_on_commit=False)
    captured_histories: list[list[dict]] = []

    async def fake_stream(system_prompt, conversation_history, caller_context, **kwargs):
        captured_histories.append(conversation_history)
        if len(captured_histories) == 1:
            on_tool_event = kwargs["on_tool_event"]
            on_tool_event(
                {
                    "phase": "dispatched",
                    "tool": "book_appointment",
                    "tool_call_id": "tc1",
                    "arguments": json.dumps(
                        {"start_time": "2026-01-01T10:00:00", "attendee_email": "a@b.com"}
                    ),
                }
            )
            on_tool_event(
                {
                    "phase": "result",
                    "tool": "book_appointment",
                    "tool_call_id": "tc1",
                    "duration_ms": 5,
                    "result": {"booked": True, "confirmation_id": "conf123"},
                }
            )
            yield "Booked!"
        else:
            yield "Anything else?"

    with (
        patch("backend.api.retell_ws.AsyncSessionLocal", test_session_factory),
        patch("backend.services.llm_service.stream_agent_response", fake_stream),
        patch("backend.api.retell_ws.call_ws.publish_call_event", AsyncMock()),
    ):
        with TestClient(app) as client:
            with client.websocket_connect(f"/llm-websocket/{call_external_id}") as ws:
                ws.receive_json()  # config
                ws.send_json(
                    {
                        "interaction_type": "response_required",
                        "response_id": 1,
                        "transcript": [{"role": "user", "content": "book it"}],
                    }
                )
                _recv_until_complete(ws)

                ws.send_json(
                    {
                        "interaction_type": "response_required",
                        "response_id": 2,
                        "transcript": [
                            {"role": "user", "content": "book it"},
                            {"role": "agent", "content": "Booked!"},
                            {"role": "user", "content": "thanks, anything else?"},
                        ],
                    }
                )
                _recv_until_complete(ws)

    assert len(captured_histories) == 2
    second_history = captured_histories[1]
    ledger_messages = [m for m in second_history if m.get("role") == "system"]
    assert len(ledger_messages) == 1
    note = ledger_messages[0]["content"]
    assert "Already completed" in note
    assert "book_appointment" in note
    assert "conf123" in note
    # The ledger note is injected ahead of the real conversation, not appended.
    assert second_history[0] is ledger_messages[0]


class TestFindDuplicateLedgerEntry:
    """_find_duplicate_ledger_entry — the matching half of the server-enforced ledger
    check (ADR-009 §4c / phase4.md Session 8, shipped 2026-08-05 after outliers.md §1's
    real double-booking)."""

    def test_matches_on_tool_and_normalized_args(self):
        completed = [
            {
                "tool": "book_appointment",
                "args": {"start_time": "2026-08-06T16:00:00", "attendee_email": "a@b.com"},
                "result_id": "23401802",
            }
        ]
        entry = _find_duplicate_ledger_entry(
            "book_appointment",
            {
                "start_time": "2026-08-06T16:00:00",
                "attendee_email": "a@b.com",
                "attendee_name": "Ali",
            },
            completed,
        )
        assert entry is not None
        assert entry["result_id"] == "23401802"

    def test_no_match_returns_none(self):
        completed = [
            {
                "tool": "book_appointment",
                "args": {"start_time": "2026-08-06T16:00:00", "attendee_email": "a@b.com"},
                "result_id": "23401802",
            }
        ]
        # Different time — same email, genuinely a different request.
        entry = _find_duplicate_ledger_entry(
            "book_appointment",
            {"start_time": "2026-08-06T16:30:00", "attendee_email": "a@b.com"},
            completed,
        )
        assert entry is None

    def test_untracked_tool_never_matches(self):
        """lookup_customer isn't in _LEDGER_ARG_KEYS — repeating a read is harmless, so
        it must never be blocked, even against a coincidentally-identical ledger entry."""
        completed = [{"tool": "lookup_customer", "args": {"x": "y"}, "result_id": ""}]
        entry = _find_duplicate_ledger_entry("lookup_customer", {"x": "y"}, completed)
        assert entry is None

    def test_empty_ledger_never_matches(self):
        assert _find_duplicate_ledger_entry("book_appointment", {"start_time": "t"}, []) is None

    def test_cancel_and_reschedule_match_on_booking_uid(self):
        """outliers.md §5: cancel/reschedule identify WHICH booking they act on, not a
        date/email like book_appointment — booking_uid is the identifying argument."""
        completed = [
            {"tool": "cancel_appointment", "args": {"booking_uid": "abc123"}, "result_id": ""},
            {
                "tool": "reschedule_appointment",
                "args": {"booking_uid": "old-uid"},
                "result_id": "23458118",
                "extras": {"booking_uid": "new-uid"},
            },
        ]
        assert (
            _find_duplicate_ledger_entry("cancel_appointment", {"booking_uid": "abc123"}, completed)
            is not None
        )
        assert (
            _find_duplicate_ledger_entry(
                "reschedule_appointment", {"booking_uid": "old-uid"}, completed
            )
            is not None
        )

    def test_reschedule_using_the_new_post_reschedule_uid_is_not_a_duplicate(self):
        """The uid-rotation self-resolution the plan relies on: after a successful
        reschedule the ledger entry is keyed on the OLD uid it acted on, so a genuine
        follow-up reschedule of the SAME appointment — using the NEW uid the first call
        returned — is a different key and must not be blocked."""
        completed = [
            {
                "tool": "reschedule_appointment",
                "args": {"booking_uid": "old-uid"},
                "result_id": "23458118",
                "extras": {"booking_uid": "new-uid"},
            }
        ]
        entry = _find_duplicate_ledger_entry(
            "reschedule_appointment", {"booking_uid": "new-uid"}, completed
        )
        assert entry is None

    def test_book_discovery_call_matches_on_phone_and_preferred_time(self):
        """Same class of bug outliers.md §1 documented and fixed for book_appointment —
        book_discovery_call is a real (if lightweight) side-effecting booking capture,
        not a read, so a repeat request for the same caller/slot must be caught too."""
        completed = [
            {
                "tool": "book_discovery_call",
                "args": {"phone": "+15551234567", "preferred_time": "tomorrow at 2pm"},
                "result_id": "",
            }
        ]
        entry = _find_duplicate_ledger_entry(
            "book_discovery_call",
            {"name": "Ali", "phone": "+15551234567", "preferred_time": "tomorrow at 2pm"},
            completed,
        )
        assert entry is not None

        # Different preferred_time — same caller, genuinely a different request.
        assert (
            _find_duplicate_ledger_entry(
                "book_discovery_call",
                {"name": "Ali", "phone": "+15551234567", "preferred_time": "Friday morning"},
                completed,
            )
            is None
        )


class TestLedgerEntry:
    def test_book_appointment_captures_booking_uid_as_an_extra(self):
        """outliers.md §5: without this, cancel_appointment/reschedule_appointment have
        no way to identify which real Cal.com booking to act on — the numeric
        confirmation_id alone is insufficient (Cal.com's cancel/reschedule endpoints key
        on the string uid)."""
        entry = _ledger_entry(
            "book_appointment",
            {"start_time": "2026-08-07T09:00:00", "attendee_email": "a@b.com"},
            {"booked": True, "confirmation_id": 23454702, "booking_uid": "1WU1GSoy6wKwjwq69nSA4U"},
        )
        assert entry["extras"] == {"booking_uid": "1WU1GSoy6wKwjwq69nSA4U"}

    def test_cancel_appointment_has_no_extras(self):
        entry = _ledger_entry(
            "cancel_appointment", {"booking_uid": "abc123"}, {"status": "cancelled"}
        )
        assert entry["extras"] == {}

    def test_uncertain_result_is_not_recorded_as_completed(self):
        """outliers.md §5: a timeout means the outcome is unconfirmed, not that it
        completed. Recording it in the ledger would tell the model something is "already
        done" that we don't actually know happened, and would block a genuine retry as a
        false duplicate."""
        entry = _ledger_entry(
            "reschedule_appointment",
            {"booking_uid": "old-uid"},
            {"status": "uncertain", "instruction": "..."},
        )
        assert entry is None


class TestDuplicateToolResult:
    def test_gives_a_positive_instruction_not_just_a_prohibition(self):
        """outliers.md §1: a bare "don't repeat this" system-prompt note lost to an
        ambiguous caller follow-up on a real call. The synthetic result must tell the
        model what to DO (inform the caller), not just what not to do."""
        entry = {"tool": "book_appointment", "args": {}, "result_id": "23401802"}
        result = _duplicate_tool_result("book_appointment", entry)

        assert result["already_completed"] is True
        assert result["reference"] == "23401802"
        instruction = result["instruction"].lower()
        assert "23401802" in result["instruction"]
        # A positive action, not only a negative constraint.
        assert "tell the caller" in instruction
        assert "already done" in instruction or "already completed" in instruction

    def test_surfaces_extras_so_a_duplicate_reschedule_gets_the_current_uid(self):
        """outliers.md §5: a duplicate reschedule_appointment request matches on the OLD
        booking_uid it was asked to act on, but anything the model does next needs the
        NEW uid the first, successful call already returned — not the stale value it
        just sent again."""
        entry = {
            "tool": "reschedule_appointment",
            "args": {"booking_uid": "old-uid"},
            "result_id": "23458118",
            "extras": {"booking_uid": "new-uid"},
        }
        result = _duplicate_tool_result("reschedule_appointment", entry)

        assert result["booking_uid"] == "new-uid"
        assert "new-uid" in result["instruction"]


class TestLedgerNote:
    def test_renders_extras_inline(self):
        entries = [
            _ledger_entry(
                "book_appointment",
                {"start_time": "2026-08-07T09:00:00", "attendee_email": "a@b.com"},
                {"confirmation_id": 23454702, "booking_uid": "1WU1GSoy6wKwjwq69nSA4U"},
            )
        ]
        note = _ledger_note(entries)
        assert "booking_uid=1WU1GSoy6wKwjwq69nSA4U" in note

    def test_entry_without_extras_renders_without_brackets(self):
        entries = [
            _ledger_entry("cancel_appointment", {"booking_uid": "abc123"}, {"status": "cancelled"})
        ]
        note = _ledger_note(entries)
        assert "[" not in note.split("\n", 1)[1]


def test_llm_websocket_duplicate_request_skips_real_dispatch_and_reaches_check_duplicate(
    tmp_path,
):
    """End-to-end proof that retell_ws._check_duplicate is actually wired into
    stream_agent_response's check_duplicate kwarg — a second turn requesting the exact
    slot already on the ledger must be intercepted before any real handler call, with the
    duplicate-aware synthetic result reaching the tool-call loop instead."""
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'dup_check.db'}"
    tenant_id = uuid.uuid4()
    agent_id = uuid.uuid4()
    call_external_id = "call_dup_check_1"
    _seed_db(db_url, agent_id, tenant_id, call_external_id, system_prompt="You are Ali.")

    test_engine = create_async_engine(db_url, poolclass=NullPool)
    test_session_factory = async_sessionmaker(test_engine, expire_on_commit=False)
    captured_check_results: list[object] = []

    async def fake_stream(system_prompt, conversation_history, caller_context, **kwargs):
        on_tool_event = kwargs["on_tool_event"]
        check_duplicate = kwargs["check_duplicate"]
        booking_args = {"start_time": "2026-08-06T16:00:00", "attendee_email": "a@b.com"}

        # Turn 1: nothing on the ledger yet — must NOT be intercepted.
        first_check = check_duplicate("book_appointment", booking_args)
        captured_check_results.append(first_check)
        if first_check is None:
            on_tool_event(
                {
                    "phase": "dispatched",
                    "tool": "book_appointment",
                    "tool_call_id": "tc1",
                    "arguments": json.dumps(booking_args),
                }
            )
            on_tool_event(
                {
                    "phase": "result",
                    "tool": "book_appointment",
                    "tool_call_id": "tc1",
                    "duration_ms": 5,
                    "result": {"booked": True, "confirmation_id": "conf123"},
                }
            )
            yield "Booked for four PM."
            return

        # Turn 2: the exact same request — must be intercepted this time.
        yield "You're already booked for that time."

    with (
        patch("backend.api.retell_ws.AsyncSessionLocal", test_session_factory),
        patch("backend.services.llm_service.stream_agent_response", fake_stream),
        patch("backend.api.retell_ws.call_ws.publish_call_event", AsyncMock()),
    ):
        with TestClient(app) as client:
            with client.websocket_connect(f"/llm-websocket/{call_external_id}") as ws:
                ws.receive_json()  # config
                ws.send_json(
                    {
                        "interaction_type": "response_required",
                        "response_id": 1,
                        "transcript": [{"role": "user", "content": "book four PM"}],
                    }
                )
                _recv_until_complete(ws)

                ws.send_json(
                    {
                        "interaction_type": "response_required",
                        "response_id": 2,
                        "transcript": [
                            {"role": "user", "content": "book four PM"},
                            {"role": "agent", "content": "Booked for four PM."},
                            {"role": "user", "content": "four PM?"},
                        ],
                    }
                )
                frames = _recv_until_complete(ws)

    assert captured_check_results[0] is None
    assert captured_check_results[1] is not None
    assert captured_check_results[1]["already_completed"] is True
    assert captured_check_results[1]["reference"] == "conf123"
    assert "conf123" in captured_check_results[1]["instruction"]
    assert "".join(f["content"] for f in frames) == "You're already booked for that time."
