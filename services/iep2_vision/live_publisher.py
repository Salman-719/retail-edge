"""Optional live-frame publisher — writes per-frame detections to a Redis stream.

Toggled by Iep2Settings.live_stream_enabled (default False).
Set enabled=False and this module is a no-op; the pipeline is unaffected.
"""
import json
import logging

log = logging.getLogger("iep2.live_publisher")

_STREAM_PREFIX = "stream:iep2:live"
_MAXLEN = 500


class LivePublisher:
    """Publishes per-frame detection payloads to stream:iep2:live:{camera_id}."""

    def __init__(self, camera_id: str, redis_url: str, enabled: bool = False):
        self._camera_id = camera_id
        self._enabled = enabled
        self._redis = None
        if enabled:
            try:
                import redis as _redis_lib  # lazy — safe to import even if not installed
                self._redis = _redis_lib.Redis.from_url(redis_url)
            except ImportError:
                log.warning("redis package not installed — LivePublisher disabled")
                self._enabled = False

    def publish(self, s3_key: str, timestamp_ms: int, frame_dets: list) -> None:
        """Push one frame's detections to the live Redis stream.

        Never raises. On Redis failure logs a warning and returns.
        frame_dets: display_tracks list from runtime (track dicts with scaled bbox coords).
        """
        if not self._enabled or self._redis is None:
            return
        try:
            detections = []
            for t in frame_dets:
                bbox = t.get("bbox", [0, 0, 0, 0])
                detections.append({
                    "track_id": t["track_id"],
                    "local_id": t.get("local_id"),
                    "x1": int(bbox[0]),
                    "y1": int(bbox[1]),
                    "x2": int(bbox[2]),
                    "y2": int(bbox[3]),
                    "confidence": float(t.get("confidence", 0.0)),
                })
            payload = json.dumps({
                "camera_id": self._camera_id,
                "timestamp_ms": timestamp_ms,
                "s3_key": s3_key or "",
                "detections": detections,
            })
            stream_key = f"{_STREAM_PREFIX}:{self._camera_id}"
            self._redis.xadd(stream_key, {"data": payload}, maxlen=_MAXLEN, approximate=True)
        except Exception as exc:
            log.warning("LivePublisher.publish failed camera=%s: %s", self._camera_id, exc)
