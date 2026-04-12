"""Redis client for IEP2.

Async client used in FastAPI endpoints.
Sync client used inside background tracking threads.
"""
import json
import redis
import redis.asyncio as aioredis

from app.core.config import settings


class AsyncRedisClient:
    def __init__(self):
        self._client: aioredis.Redis | None = None

    async def connect(self):
        self._client = aioredis.from_url(
            settings.REDIS_URL, encoding="utf-8", decode_responses=True
        )

    async def _ensure(self):
        if self._client is None:
            await self.connect()

    async def hgetall(self, name: str) -> dict:
        await self._ensure()
        return await self._client.hgetall(name)

    async def exists(self, key: str) -> bool:
        await self._ensure()
        return bool(await self._client.exists(key))

    async def delete(self, *keys: str):
        await self._ensure()
        await self._client.delete(*keys)

    async def close(self):
        if self._client:
            await self._client.aclose()


class SyncRedisClient:
    """Sync client for use inside daemon threads."""
    def __init__(self):
        self._client = redis.from_url(settings.REDIS_URL, decode_responses=True)

    def set_job(self, camera_id: str, data: dict):
        key = f"job:{camera_id}:tracking"
        self._client.hset(key, mapping={k: json.dumps(v) if isinstance(v, (dict, list)) else str(v) for k, v in data.items()})
        self._client.expire(key, 3600)  # 1 hour TTL

    def update_job(self, camera_id: str, **fields):
        key = f"job:{camera_id}:tracking"
        self._client.hset(key, mapping={k: json.dumps(v) if isinstance(v, (dict, list)) else str(v) for k, v in fields.items()})


async_redis = AsyncRedisClient()
sync_redis = SyncRedisClient()


def job_key(camera_id: str) -> str:
    return f"job:{camera_id}:tracking"
