"""IEP1 observability -- per-camera Prometheus metrics (private registry, same
pattern as IEP2/IEP3). ``iep1_camera_status`` and ``iep1_window_captured_ratio``
are the key health signals for camera-disconnection dashboards."""

from __future__ import annotations

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, start_http_server

REGISTRY = CollectorRegistry()

frames_captured = Counter(
    "iep1_frames_captured_total", "Frames captured", ["camera_id"], registry=REGISTRY
)
frames_dropped = Counter(
    "iep1_frames_dropped_total", "Frames dropped", ["camera_id", "reason"], registry=REGISTRY
)  # reason: read_fail | s3_fail | queue_overflow
window_captured_ratio = Gauge(
    "iep1_window_captured_ratio", "captured/expected per window", ["camera_id"], registry=REGISTRY
)
camera_status = Gauge(
    "iep1_camera_status", "0 offline / 1 degraded / 2 online", ["camera_id"], registry=REGISTRY
)
s3_upload_seconds = Histogram(
    "iep1_s3_upload_seconds", "Per-frame S3 upload latency", ["camera_id"], registry=REGISTRY
)
window_publish = Counter(
    "iep1_window_publish_total", "Windows published", ["camera_id", "status"], registry=REGISTRY
)

_STATUS_VALUE = {"offline": 0, "degraded": 1, "online": 2}


def emit_health(manifest) -> None:
    """Update the per-window gauges/counters from a closed manifest."""
    cam = manifest.camera_id
    ratio = (manifest.captured_frames / manifest.expected_frames) if manifest.expected_frames else 0.0
    window_captured_ratio.labels(cam).set(ratio)
    camera_status.labels(cam).set(_STATUS_VALUE.get(manifest.camera_status, 0))
    window_publish.labels(cam, manifest.camera_status).inc()


def start_metrics_server(port: int) -> None:
    """Expose the IEP1 metrics registry on ``port`` (/metrics)."""
    start_http_server(port, registry=REGISTRY)
