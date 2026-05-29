"""batch_complete emission to a Redis Stream consumed by IEP3's coordinator
(IEP3 spec §2)."""

from __future__ import annotations

from common.config import get_settings


class BatchEventEmitter:
    STREAM = "stream:iep2:batch_complete"

    def __init__(self, redis_url: str | None = None):
        import redis.asyncio as redis  # lazy: keeps redis optional for non-event paths

        self._r = redis.from_url(redis_url or get_settings().REDIS_URL)

    async def emit(
        self, store_id: str, camera_id: str, batch_number: int, window_start_ms: int, window_end_ms: int
    ) -> None:
        await self._r.xadd(
            self.STREAM,
            {
                "store_id": str(store_id),
                "camera_id": camera_id,
                "batch_number": str(batch_number),
                "window_start_ms": str(window_start_ms),
                "window_end_ms": str(window_end_ms),
            },
        )

    async def close(self) -> None:
        await self._r.aclose()
