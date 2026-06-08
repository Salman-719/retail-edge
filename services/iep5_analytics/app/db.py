"""asyncpg connection pool for IEP5 (one-shot job). Small pool — the whole job
runs in a single transaction on one connection.
"""
from __future__ import annotations

import logging

import asyncpg

logger = logging.getLogger(__name__)

_pool: asyncpg.Pool | None = None


async def create_pool(database_url: str) -> asyncpg.Pool:
    global _pool
    _pool = await asyncpg.create_pool(
        dsn=database_url,
        min_size=1,
        max_size=4,
        command_timeout=120,
        statement_cache_size=0,  # PgBouncer-safe
    )
    logger.info("asyncpg pool created (min=1, max=4)")
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
