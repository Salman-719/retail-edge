import redis.asyncio as aioredis
from app.core.config import settings

# Key naming conventions:
#   store:{store_id}:person:{person_id}       → active person record
#   store:{store_id}:chunk_backlog            → list of pending chunks
#   job:{camera_id}:tracking                 → tracking job state
#   carryover:{store_id}:{camera_id}         → chunk carryover payload


class RedisClient:
    def __init__(self):
        self._client: aioredis.Redis | None = None

    async def connect(self):
        self._client = aioredis.from_url(
            settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
        )

    async def ping(self) -> bool:
        if self._client is None:
            await self.connect()
        return await self._client.ping()

    async def get(self, key: str):
        if self._client is None:
            await self.connect()
        return await self._client.get(key)

    async def set(self, key: str, value: str, ex: int | None = None):
        if self._client is None:
            await self.connect()
        await self._client.set(key, value, ex=ex)

    async def delete(self, *keys: str):
        if self._client is None:
            await self.connect()
        await self._client.delete(*keys)

    async def hset(self, name: str, mapping: dict):
        if self._client is None:
            await self.connect()
        await self._client.hset(name, mapping=mapping)

    async def hgetall(self, name: str) -> dict:
        if self._client is None:
            await self.connect()
        return await self._client.hgetall(name)

    async def publish(self, channel: str, message: str):
        if self._client is None:
            await self.connect()
        await self._client.publish(channel, message)

    async def close(self):
        if self._client:
            await self._client.aclose()


redis_client = RedisClient()
