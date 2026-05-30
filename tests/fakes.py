"""In-memory fakes for S3 and Redis streams, shared across IEP1/IEP2 tests.

These mirror only the surface the code uses:
- ``FakeS3`` -> the ``common.s3.S3Client`` async API (put_bytes/get_bytes/get_image/ensure_bucket).
- ``FakeRedisStream`` -> the subset of redis.asyncio used by the publisher and the
  IEP2 RedisStreamFrameSource (xadd / xgroup_create / xreadgroup / xack).
"""

from __future__ import annotations

import numpy as np


class FakeS3:
    """Dict-backed S3 stand-in. Stores raw bytes by key; decodes images with cv2."""

    def __init__(self):
        self.store: dict[str, bytes] = {}
        self.ensured = False

    async def put_bytes(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
        self.store[key] = data

    async def get_bytes(self, key: str) -> bytes | None:
        return self.store.get(key)

    async def get_image(self, key: str):
        data = self.store.get(key)
        if not data:
            return None
        import cv2

        arr = np.frombuffer(data, dtype=np.uint8)
        return cv2.imdecode(arr, cv2.IMREAD_COLOR)

    async def ensure_bucket(self) -> None:
        self.ensured = True


class FakeRedisStream:
    """Minimal Redis-streams stand-in. Supports one consumer group per stream and
    ``>`` reads (new, unacked messages), enough for publisher + consumer tests."""

    def __init__(self):
        # stream -> list of (msg_id, {field: bytes})
        self._streams: dict[str, list[tuple[bytes, dict]]] = {}
        self._groups: dict[tuple[str, str], int] = {}  # (stream, group) -> next index
        self._seq = 0

    async def xadd(self, stream: str, fields: dict) -> bytes:
        self._seq += 1
        msg_id = f"{self._seq}-0".encode()
        encoded = {
            (k.encode() if isinstance(k, str) else k): (v.encode() if isinstance(v, str) else v)
            for k, v in fields.items()
        }
        self._streams.setdefault(stream, []).append((msg_id, encoded))
        return msg_id

    async def xgroup_create(self, stream: str, group: str, id: str = "0", mkstream: bool = False) -> None:
        self._streams.setdefault(stream, [])
        self._groups[(stream, group)] = 0

    async def xreadgroup(self, group, consumer, streams: dict, count=1, block=None):
        out = []
        for stream, _ in streams.items():
            entries = self._streams.get(stream, [])
            idx = self._groups.get((stream, group), 0)
            batch = entries[idx: idx + count]
            if batch:
                self._groups[(stream, group)] = idx + len(batch)
                out.append((stream.encode(), batch))
        return out

    async def xack(self, stream: str, group: str, msg_id) -> int:
        return 1

    async def xrange(self, stream: str, count: int | None = None):
        entries = self._streams.get(stream, [])
        return entries[:count] if count else list(entries)

    async def xrevrange(self, stream: str, count: int | None = None):
        entries = list(reversed(self._streams.get(stream, [])))
        return entries[:count] if count else entries

    def message_count(self, stream: str) -> int:
        return len(self._streams.get(stream, []))
