"""Shared pytest fixtures: async test DB session, FastAPI test client,
and a mock voice platform adapter so tests never hit real Retell/Vapi APIs.
"""

import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from jose import jwt
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.config import get_settings
from backend.database import get_db
from backend.main import app
from backend.models.base import Base

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine(TEST_DATABASE_URL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session

    await engine.dispose()


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """FastAPI test client wired to the in-memory test DB, never the real one.

    Without this override, routes depending on get_db would fall through to the
    app's real AsyncSessionLocal (settings.database_url) — dangerous in this repo
    specifically, since the host-side DATABASE_URL port has been found to collide
    with an unrelated project's live Postgres container.
    """

    async def _override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def queued_research(monkeypatch) -> list[str]:
    """Capture research_prospect.delay() instead of dispatching it, and yield the ids.

    Autouse because CELERY_TASK_ALWAYS_EAGER is false in this environment, so a bare
    .delay() would try to reach the real Redis broker — every test that uploads a CSV or
    hits /discover would depend on a running broker and stall on the publish retry when
    there isn't one. Tests that care about enqueueing assert on this list.
    """
    from backend.workers import prospect_tasks

    queued: list[str] = []
    monkeypatch.setattr(
        prospect_tasks.research_prospect, "delay", lambda prospect_id: queued.append(prospect_id)
    )
    monkeypatch.setattr(prospect_tasks.discover_prospects, "delay", lambda *a, **kw: None)
    return queued


@pytest.fixture
def tenant_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def other_tenant_id() -> uuid.UUID:
    """A second tenant, for asserting cross-tenant isolation (ADR-001)."""
    return uuid.uuid4()


def make_token(tenant_id: uuid.UUID) -> str:
    """Mint a bearer token the way backend/api/deps.py expects to receive one."""
    settings = get_settings()
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "tenant_id": str(tenant_id),
            "sub": f"test-user@{tenant_id}",
            "iat": now,
            "exp": now + timedelta(hours=1),
        },
        settings.jwt_secret,
        algorithm="HS256",
    )


@pytest.fixture
def auth_headers(tenant_id: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {make_token(tenant_id)}"}


@pytest.fixture
def other_auth_headers(other_tenant_id: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {make_token(other_tenant_id)}"}


class MockVoicePlatformAdapter:
    """Drop-in replacement for RetellAdapter/VapiAdapter in tests."""

    async def create_agent(self, name: str, system_prompt: str, voice_config: dict) -> str:
        return "mock-agent-id"

    async def assign_phone_number(self, agent_external_id: str, number: str) -> None:
        pass

    async def send_response(self, call_external_id: str, text: str) -> None:
        pass

    def parse_webhook(self, payload: dict) -> dict:
        return {
            "event": payload.get("event", "unknown"),
            "call_id": "mock-call",
            "transcript": None,
        }


@pytest.fixture
def mock_voice_adapter() -> MockVoicePlatformAdapter:
    return MockVoicePlatformAdapter()
