from typing import AsyncGenerator
import redis.asyncio as redis
from app.core.config import settings
from app.core.resilience import REDIS_CONNECT_TIMEOUT_S, REDIS_SOCKET_TIMEOUT_S

_pool: redis.ConnectionPool | None = None


def _get_pool() -> redis.ConnectionPool:
    global _pool
    if _pool is None:
        # Bounded socket timeouts so a stalled Redis never hangs a request; idle
        # pooled sockets are health-checked before reuse.
        _pool = redis.ConnectionPool.from_url(
            settings.REDIS_URL,
            decode_responses=False,
            socket_timeout=REDIS_SOCKET_TIMEOUT_S,
            socket_connect_timeout=REDIS_CONNECT_TIMEOUT_S,
            health_check_interval=30,
        )
    return _pool


async def get_redis() -> AsyncGenerator[redis.Redis, None]:
    r = redis.Redis(connection_pool=_get_pool())
    try:
        yield r
    finally:
        await r.aclose()
