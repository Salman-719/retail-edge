"""asyncpg connection pool for IEP4.
One pool per process. All persistence operations acquire from this pool.
IEP4 connects directly to PostgreSQL (via PgBouncer) — no ORM, no SQLAlchemy.
"""
from __future__ import annotations

import logging

import asyncpg

logger = logging.getLogger(__name__)

_pool: asyncpg.Pool | None = None


async def create_pool(database_url: str) -> asyncpg.Pool:
    """Create the module-level asyncpg pool. Call once at startup."""
    global _pool
    _pool = await asyncpg.create_pool(
        dsn=database_url,
        min_size=2,
        max_size=10,
        command_timeout=30,
        statement_cache_size=0,  # PgBouncer-safe: no server-side prepared stmts
    )
    logger.info("asyncpg pool created (min=2, max=10)")
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
        logger.info("asyncpg pool closed")


def get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("DB pool not initialized — call create_pool() at startup")
    return _pool
