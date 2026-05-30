"""IEP1-integrated frame source.

Consumes IEP1's per-camera manifest stream (``stream:iep1:{camera_id}``) and
yields whole **windows**: IEP1 already defined the batch boundary, so IEP2 must
not re-window. One manifest = one batch = one ``batch_complete``, making batch
alignment between IEP1, IEP2 and IEP3 exact by construction.

Frames are fetched from S3 by key; the **capture timestamp is parsed from the
key** (``frames/cam/{ts}.jpg``), never recomputed — with gaps the frames are not
evenly spaced, and the spatial-temporal gate needs the true elapsed time.

This is the production/demo counterpart of ``VideoFrameSource`` (kept for the
standalone/test path). Redis is imported lazily and the client is injectable so
tests use an in-memory fake.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from common.config import get_settings


@dataclass
class WindowBatch:
    """One IEP1 window as IEP2 consumes it (replaces the implicit frame-count batch)."""

    batch_number: int
    window_start_ms: int
    window_end_ms: int
    camera_status: str  # online | degraded | offline
    expected_frames: int
    captured_frames: int
    frame_keys: list[str]
    gaps: list[dict]  # [{start_ms, end_ms, missing_frames}]

    @property
    def is_empty(self) -> bool:
        return self.camera_status == "offline" or not self.frame_keys


class RedisStreamFrameSource:
    def __init__(self, camera_id: str, s3_client, redis_client=None, settings=None):
        self._cam = camera_id
        self._s = settings or get_settings()
        self._stream = f"stream:iep1:{camera_id}"
        self._group = f"iep2:{camera_id}"
        self._s3 = s3_client
        self._redis = redis_client  # injectable; lazily created if None

    def _client(self):
        if self._redis is None:
            import redis.asyncio as redis

            self._redis = redis.from_url(self._s.REDIS_URL)
        return self._redis

    async def windows(self):
        """Yield ``(WindowBatch, msg_id)`` for each manifest, at-least-once
        (caller acks after successful processing)."""
        client = self._client()
        try:
            await client.xgroup_create(self._stream, self._group, id="0", mkstream=True)
        except Exception:  # noqa: BLE001 - group already exists (BUSYGROUP)
            pass
        while True:
            msgs = await client.xreadgroup(
                self._group, "c1", {self._stream: ">"}, count=1, block=5000
            )
            if not msgs:
                continue
            for _stream, entries in msgs:
                for msg_id, fields in entries:
                    manifest = json.loads(fields[b"manifest"])
                    yield self._to_batch(manifest), msg_id

    @staticmethod
    def _to_batch(m: dict) -> WindowBatch:
        return WindowBatch(
            batch_number=m["batch_number"],
            window_start_ms=m["window_start_ms"],
            window_end_ms=m["window_end_ms"],
            camera_status=m["camera_status"],
            expected_frames=m["expected_frames"],
            captured_frames=m["captured_frames"],
            frame_keys=list(m.get("frame_keys", [])),
            gaps=list(m.get("gaps", [])),
        )

    async def fetch_frames(self, batch: WindowBatch):
        """Yield ``(capture_ts_ms, frame)`` for each key in chronological order;
        skip keys that fail to fetch (already counted as gaps by IEP1). Keys are
        ordered by their parsed capture timestamp (NOT lexically -- ``1000.jpg``
        would sort before ``200.jpg`` as a string, scrambling the timeline)."""
        for key in sorted(batch.frame_keys, key=self._ts_from_key):
            frame = await self._s3.get_image(key)
            if frame is not None:
                yield self._ts_from_key(key), frame

    @staticmethod
    def _ts_from_key(key: str) -> int:
        # frames/cam_01/1717075391200.jpg -> 1717075391200
        return int(key.rsplit("/", 1)[-1].split(".")[0])

    async def ack(self, msg_id) -> None:
        await self._client().xack(self._stream, self._group, msg_id)
