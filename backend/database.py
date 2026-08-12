"""Async SQLAlchemy engine and session management."""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.config import get_settings

settings = get_settings()

engine = create_async_engine(
    settings.database_url,
    echo=settings.environment == "development",
    # Neon closes idle connections after a few minutes; pre_ping detects a dead
    # connection before use and transparently reconnects instead of raising
    # asyncpg.InterfaceError, and pool_recycle keeps connections from sitting
    # idle long enough to hit that timeout in the first place.
    pool_pre_ping=True,
    pool_recycle=300,
)

AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency — yields a scoped DB session per request."""
    async with AsyncSessionLocal() as session:
        yield session
