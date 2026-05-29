"""Async database layer shared by IEP2 and IEP3.

A single process-wide async engine with connection pooling. Sessions are handed
out via ``session_scope()`` so every caller gets correct commit/rollback/close
semantics. Reuses the same ``DATABASE_URL`` the rest of the repo uses; this is a
separate engine from EEP's (each process owns one), not a second connection to
the same in-process engine.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from common.config import get_settings

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    """Lazily create the process-wide async engine with a connection pool."""
    global _engine
    if _engine is None:
        s = get_settings()
        _engine = create_async_engine(
            s.DATABASE_URL,
            pool_size=s.db_pool_size,
            max_overflow=s.db_max_overflow,
            pool_pre_ping=True,  # recover from dropped connections
            future=True,
        )
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            bind=get_engine(), expire_on_commit=False, class_=AsyncSession
        )
    return _session_factory


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Transactional scope. Commits on success, rolls back on exception.

    Usage:
        async with session_scope() as session:
            session.add(row)
    """
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def dispose_engine() -> None:
    """Call on service shutdown to release pool connections cleanly."""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory = None
