"""asyncpg connection pool for IEP3.
One pool per process. All repository operations acquire from this pool.
IEP3 connects directly to PostgreSQL — no ORM, no SQLAlchemy.
"""
from __future__ import annotations

import asyncpg
import logging

logger = logging.getLogger(__name__)

_pool: asyncpg.Pool | None = None


async def create_pool(database_url: str) -> asyncpg.Pool:
    """Create the module-level asyncpg connection pool.
    Call once at startup before any DB operations.
    database_url must be plain postgresql:// scheme.
    """
    global _pool
    _pool = await asyncpg.create_pool(
        dsn=database_url,
        min_size=2,
        max_size=10,
        command_timeout=30,
        statement_cache_size=0,  # PgBouncer transaction mode: disable prepared-stmt cache
    )
    logger.info("asyncpg pool created (min=2, max=10)")
    return _pool


async def close_pool() -> None:
    """Close the pool gracefully on shutdown."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
        logger.info("asyncpg pool closed")


def get_pool() -> asyncpg.Pool:
    """Return the active pool. Raises RuntimeError if called before create_pool()."""
    if _pool is None:
        raise RuntimeError(
            "DB pool not initialized — call create_pool() at startup"
        )
    return _pool
