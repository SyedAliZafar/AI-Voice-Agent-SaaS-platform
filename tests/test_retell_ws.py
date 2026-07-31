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
"""

import asyncio
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from backend.api.retell_ws import _to_conversation_history
from backend.main import app
from backend.models.agent import Agent
from backend.models.base import Base
from backend.models.call import Call


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


def test_llm_websocket_ping_pong_and_response(tmp_path):
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'happy.db'}"
    tenant_id = uuid.uuid4()
    agent_id = uuid.uuid4()
    call_external_id = "call_abc123"
    _seed_db(db_url, agent_id, tenant_id, call_external_id, system_prompt="You are Ali.")

    test_engine = create_async_engine(db_url, poolclass=NullPool)
    test_session_factory = async_sessionmaker(test_engine, expire_on_commit=False)
    mock_response = AsyncMock(return_value="Hello there!")

    with (
        patch("backend.api.retell_ws.AsyncSessionLocal", test_session_factory),
        patch("backend.services.llm_service.get_agent_response", mock_response),
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
                reply = ws.receive_json()
                assert reply["response_type"] == "response"
                assert reply["response_id"] == 7
                assert reply["content"] == "Hello there!"
                assert reply["content_complete"] is True
                assert reply["end_call"] is False

    mock_response.assert_awaited_once()
    call_args = mock_response.await_args
    assert call_args.args[0] == "You are Ali."
    assert call_args.args[1] == [{"role": "user", "content": "Hi"}]
    assert call_args.args[2]["agent_id"] == str(agent_id)
    assert call_args.args[2]["tenant_id"] == str(tenant_id)
