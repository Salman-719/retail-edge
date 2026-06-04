import collections
import dataclasses
import json
import logging

import redis

from services.iep1_ingestion.app.window import WindowManifest

logger = logging.getLogger(__name__)

STREAM_PREFIX   = "stream:iep1"
BUFFER_MAX_SIZE = 64


class WindowPublisher:
    def __init__(self, camera_id: str, redis_url: str, redis_client=None) -> None:
        self.camera_id = camera_id
        self.redis_url = redis_url
        self._client = redis_client
        self._buffer: collections.deque = collections.deque(maxlen=BUFFER_MAX_SIZE)

    def _stream_name(self) -> str:
        return f"{STREAM_PREFIX}:{self.camera_id}"

    def _ensure_client(self) -> None:
        if self._client is None:
            self._client = redis.Redis.from_url(self.redis_url)

    def _serialize(self, manifest: WindowManifest) -> str:
        return json.dumps(dataclasses.asdict(manifest))

    def _xadd(self, manifest: WindowManifest) -> None:
        self._client.xadd(
            self._stream_name(),
            {"manifest": self._serialize(manifest)},
            maxlen=1000,
            approximate=True,
        )

    def publish(self, manifest: WindowManifest) -> bool:
        try:
            self._ensure_client()
        except Exception as exc:
            self._buffer.append(manifest)
            logger.warning(
                "camera_id=%s: Redis client creation failed: %s — buffering manifest (buffer_size=%d)",
                self.camera_id, exc, len(self._buffer),
            )
            return False

        # Drain buffer first
        while self._buffer:
            buffered = self._buffer[0]
            try:
                self._xadd(buffered)
                self._buffer.popleft()
            except Exception as exc:
                self._buffer.append(manifest)
                logger.warning(
                    "camera_id=%s: Redis drain failed: %s — buffering manifest (buffer_size=%d)",
                    self.camera_id, exc, len(self._buffer),
                )
                return False

        # Publish current manifest
        try:
            self._xadd(manifest)
            return True
        except Exception as exc:
            self._buffer.append(manifest)
            logger.warning(
                "camera_id=%s: Redis publish failed: %s — buffering manifest (buffer_size=%d)",
                self.camera_id, exc, len(self._buffer),
            )
            return False


if __name__ == "__main__":
    import time
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    from services.iep1_ingestion.app.window import Gap

    now = int(time.time() * 1000)
    manifest = WindowManifest(
        window_start_ms=now,
        window_end_ms=now + 10_000,
        batch_number=1,
        status="online",
        frames=[(now + i * 200, f"frames/test-cam/{now + i * 200}.jpg") for i in range(50)],
        gaps=[],
        frame_count=50,
        expected_frames=50,
    )

    publisher = WindowPublisher(camera_id="test-cam", redis_url="redis://localhost:6379")
    ok = publisher.publish(manifest)

    if not ok:
        print("FAIL: publish returned False")
        raise SystemExit(1)

    # Read back with XRANGE and verify
    stream = f"{STREAM_PREFIX}:test-cam"
    messages = publisher._client.xrange(stream, "-", "+", count=1)
    if not messages:
        print("FAIL: no messages found in stream")
        raise SystemExit(1)

    raw = messages[-1][1][b"manifest"]
    data = json.loads(raw)
    print(f"status: {data['status']}")
