"""S3 uploader with a bounded capture->upload queue.

Frames are encoded to JPEG and written to S3 as captured, keyed by capture
timestamp (``{prefix}/{camera_id}/{capture_ts_ms}.jpg``), so numeric/lexical key
order equals chronological order and the window manifest only ever references
keys that already exist.

Two usage modes:
- ``upload(ts, frame)`` — direct async upload (with bounded retry); returns the
  key on success or None on exhaustion. Used by the capture-time video runtime.
- background queue (``submit``/``run_worker``) — the bounded drop-oldest-on-
  overflow buffer for the live/RTSP path where capture must never block on S3.
"""

from __future__ import annotations

import asyncio
import logging

import numpy as np

from common.s3 import S3Client

log = logging.getLogger(__name__)


class S3Uploader:
    def __init__(self, camera_id: str, settings, s3_client: S3Client | None = None):
        self._cam = camera_id
        self._s = settings
        self._s3 = s3_client or S3Client(settings)
        self._prefix = settings.iep1_s3_prefix
        self._queue: asyncio.Queue[tuple[int, np.ndarray]] = asyncio.Queue(
            maxsize=settings.iep1_upload_queue_max
        )
        self.dropped = 0  # frames dropped on queue overflow (become gaps)

    def key_for(self, capture_ts_ms: int) -> str:
        return f"{self._prefix}/{self._cam}/{capture_ts_ms}.jpg"

    def _encode(self, frame: np.ndarray) -> bytes | None:
        import cv2

        ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, self._s.iep1_jpeg_quality])
        return buf.tobytes() if ok else None

    async def upload(self, capture_ts_ms: int, frame: np.ndarray) -> str | None:
        """Encode + write one frame with bounded retry. Returns the S3 key on
        success, or None if encoding failed or all retries were exhausted (the
        frame then becomes a gap in the window manifest)."""
        data = self._encode(frame)
        if data is None:
            return None
        key = self.key_for(capture_ts_ms)
        delay = 0.1
        for attempt in range(self._s.iep1_s3_retry_attempts):
            try:
                await self._s3.put_bytes(key, data, content_type="image/jpeg")
                return key
            except Exception as exc:  # noqa: BLE001 - bounded retry then give up
                if attempt == self._s.iep1_s3_retry_attempts - 1:
                    log.warning("s3 upload failed for %s after %d attempts: %s",
                                key, self._s.iep1_s3_retry_attempts, exc)
                    return None
                await asyncio.sleep(delay)
                delay *= 2
        return None

    # ---- bounded background queue (live/RTSP path) ----

    def submit(self, capture_ts_ms: int, frame: np.ndarray) -> None:
        """Non-blocking enqueue; drops the oldest unsent frame on overflow so
        capture never blocks and memory stays bounded."""
        while True:
            try:
                self._queue.put_nowait((capture_ts_ms, frame))
                return
            except asyncio.QueueFull:
                try:
                    self._queue.get_nowait()
                    self.dropped += 1
                except asyncio.QueueEmpty:
                    return
