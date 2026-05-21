from typing import AsyncGenerator
import redis.asyncio as redis
from app.core.config import settings

_pool: redis.ConnectionPool | None = None


def _get_pool() -> redis.ConnectionPool:
    global _pool
    if _pool is None:
        _pool = redis.ConnectionPool.from_url(settings.REDIS_URL, decode_responses=False)
    return _pool


async def get_redis() -> AsyncGenerator[redis.Redis, None]:
    r = redis.Redis(connection_pool=_get_pool())
    try:
        yield r
    finally:
        await r.aclose()
