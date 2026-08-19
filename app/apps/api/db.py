from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from .settings import get_settings

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        s = get_settings()
        kwargs: dict = {"echo": False, "pool_pre_ping": True, "future": True}
        if not s.database_url.startswith("sqlite"):
            kwargs.update(
                pool_size=s.db_pool_size,
                max_overflow=s.db_max_overflow,
                pool_timeout=s.db_pool_timeout,
                pool_recycle=1800,
            )
        _engine = create_async_engine(s.database_url, **kwargs)
    return _engine


def sessionmaker() -> async_sessionmaker[AsyncSession]:
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = async_sessionmaker(engine(), expire_on_commit=False, autoflush=False)
    return _sessionmaker


async def get_db() -> AsyncIterator[AsyncSession]:
    async with sessionmaker()() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
