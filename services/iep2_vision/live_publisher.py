"""Optional live-frame publisher — writes per-frame detections to a Redis stream.

Toggled by Iep2Settings.live_stream_enabled (default False).
Set enabled=False and this module is a no-op; the pipeline is unaffected.

Two payload modes:
  - S3 mode (prod): payload carries `s3_key`; Live Bridge presigns it.
  - Embed mode (dev): payload carries a base64 JPEG in `frame_b64`; Live Bridge
    forwards it directly. Used when frames live in tmpfs (no S3 round-trip).
"""
import base64
import json
import logging
import uuid

log = logging.getLogger("iep2.live_publisher")

_STREAM_PREFIX = "stream:iep2:live"
_MAXLEN = 500


def _local_id_str(value) -> str | None:
    """Normalise a track local_id (int from BoTSORT, str, or None) to str|None."""
    if value is None:
        return None
    if isinstance(value, int):
        return str(uuid.UUID(int=value))
    return str(value)


class LivePublisher:
    """Publishes per-frame detection payloads to stream:iep2:live:{camera_id}."""

    def __init__(
        self,
        camera_id: str,
        redis_url: str,
        enabled: bool = False,
        embed_frame: bool = False,
        max_width: int = 640,
    ):
        self._camera_id = camera_id
        self._enabled = enabled
        self._embed_frame = embed_frame
        self._max_width = max_width
        self._redis = None
        if enabled:
            try:
                import redis as _redis_lib  # lazy — safe to import even if not installed
                self._redis = _redis_lib.Redis.from_url(redis_url)
            except ImportError:
                log.warning("redis package not installed — LivePublisher disabled")
                self._enabled = False

    # ── Embed mode: frame already in memory (tmpfs / daemon path) ───────────────

    def publish_frame(self, frame_bgr, timestamp_ms: int, tracks: list) -> None:
        """Publish one frame (BGR ndarray) plus its tracks to the live stream.

        Encodes the frame to JPEG scaled to max_width, base64-encodes it into
        `frame_b64`, and scales detection bboxes by the same factor so overlays
        align in the browser. Never raises.
        """
        if not self._enabled or self._redis is None:
            return
        try:
            import cv2

            h, w = frame_bgr.shape[:2]
            scale = (self._max_width / w) if (w > self._max_width) else 1.0

            frame_b64 = ""
            if self._embed_frame:
                frame_enc = cv2.resize(frame_bgr, (int(w * scale), int(h * scale))) if scale != 1.0 else frame_bgr
                ok, buf = cv2.imencode(".jpg", frame_enc, [cv2.IMWRITE_JPEG_QUALITY, 70])
                if ok:
                    frame_b64 = base64.b64encode(buf.tobytes()).decode("ascii")

            detections = []
            for t in tracks:
                bbox = t.get("bbox", [0, 0, 0, 0])
                det = {
                    "track_id":   t.get("track_id"),
                    "local_id":   _local_id_str(t.get("local_id")),
                    "x1": int(bbox[0] * scale),
                    "y1": int(bbox[1] * scale),
                    "x2": int(bbox[2] * scale),
                    "y2": int(bbox[3] * scale),
                    "confidence": float(t.get("confidence", 0.0)),
                }
                if t.get("floor_x") is not None:
                    det["floor_x"] = float(t["floor_x"])
                if t.get("floor_y") is not None:
                    det["floor_y"] = float(t["floor_y"])
                if t.get("reid_sim") is not None:
                    det["reid_sim"] = float(t["reid_sim"])
                if t.get("reid_matched") is not None:
                    det["reid_matched"] = bool(t["reid_matched"])
                detections.append(det)

            payload = json.dumps({
                "camera_id":    self._camera_id,
                "timestamp_ms": timestamp_ms,
                "frame_b64":    frame_b64,
                "s3_key":       "",
                "detections":   detections,
            })
            self._redis.xadd(
                f"{_STREAM_PREFIX}:{self._camera_id}",
                {"data": payload}, maxlen=_MAXLEN, approximate=True,
            )
        except Exception as exc:
            log.warning("LivePublisher.publish_frame failed camera=%s: %s", self._camera_id, exc)

    # ── S3 mode: frame stored in object storage (prod path) ─────────────────────

    def publish(self, s3_key: str, timestamp_ms: int, frame_dets: list) -> None:
        """Push one frame's detections (S3 mode) to the live Redis stream.

        Never raises. On Redis failure logs a warning and returns.
        frame_dets: display_tracks list from runtime (track dicts with bbox coords).
        """
        if not self._enabled or self._redis is None:
            return
        try:
            detections = []
            for t in frame_dets:
                bbox = t.get("bbox", [0, 0, 0, 0])
                det = {
                    "track_id": t["track_id"],
                    "local_id": _local_id_str(t.get("local_id")),
                    "x1": int(bbox[0]),
                    "y1": int(bbox[1]),
                    "x2": int(bbox[2]),
                    "y2": int(bbox[3]),
                    "confidence": float(t.get("confidence", 0.0)),
                }
                if t.get("reid_sim") is not None:
                    det["reid_sim"] = float(t["reid_sim"])
                if t.get("reid_matched") is not None:
                    det["reid_matched"] = bool(t["reid_matched"])
                detections.append(det)
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
