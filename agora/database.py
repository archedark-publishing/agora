"""Async SQLAlchemy engine and session utilities."""

from collections.abc import AsyncIterator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from agora.config import get_settings

settings = get_settings()

engine = create_async_engine(
    settings.database_url,
    echo=settings.environment.lower() == "development",
    pool_pre_ping=True,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db_session() -> AsyncIterator[AsyncSession]:
    """Yield an async database session for request handlers."""

    async with AsyncSessionLocal() as session:
        yield session


async def run_health_query(session: AsyncSession) -> None:
    """Run a tiny query to verify database connectivity."""

    await session.execute(text("SELECT 1"))


async def close_engine() -> None:
    """Dispose DB connections during application shutdown."""

    await engine.dispose()
