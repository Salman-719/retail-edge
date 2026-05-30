"""Window manifest publisher -- one message per window on the per-camera stream.

Publishes to ``stream:iep1:{camera_id}`` so IEP2's ``RedisStreamFrameSource``
consumes exactly one manifest = one batch = one ``batch_complete``. Redis is
imported lazily and the client is injectable so tests use an in-memory fake.
If Redis is unreachable, manifests are buffered (bounded, drop-oldest) and
replayed on the next successful publish -- frames are already in S3, so a delayed
manifest is still valid.
"""

from __future__ import annotations

import json
import logging
from collections import deque
from dataclasses import asdict

from common.config import get_settings

log = logging.getLogger(__name__)


def _ser(obj):
    # Gap is a dataclass; asdict already expanded it, but keep a default for safety.
    if hasattr(obj, "__dict__"):
        return obj.__dict__
    raise TypeError(f"not JSON serializable: {type(obj)!r}")


class WindowPublisher:
    def __init__(self, camera_id: str, redis_client=None, settings=None):
        self._s = settings or get_settings()
        self._stream = f"stream:iep1:{camera_id}"
        self._redis = redis_client  # injectable; lazily created if None
        self._buffer: deque = deque(maxlen=self._s.iep1_manifest_buffer_max)

    def _client(self):
        if self._redis is None:
            import redis.asyncio as redis

            self._redis = redis.from_url(self._s.REDIS_URL)
        return self._redis

    async def publish(self, manifest) -> bool:
        """Publish a manifest (replaying any buffered ones first). Returns True if
        this manifest reached Redis, False if it was buffered for retry."""
        payload = json.dumps(asdict(manifest), default=_ser)
        try:
            client = self._client()
            await self._drain_buffer(client)
            await client.xadd(self._stream, {"manifest": payload})
            return True
        except Exception as exc:  # noqa: BLE001 - buffer and retry next window
            log.warning("redis publish failed for %s (buffering): %s", self._stream, exc)
            self._buffer.append(payload)  # drop-oldest beyond cap via deque maxlen
            return False

    async def _drain_buffer(self, client) -> None:
        while self._buffer:
            await client.xadd(self._stream, {"manifest": self._buffer[0]})
            self._buffer.popleft()
