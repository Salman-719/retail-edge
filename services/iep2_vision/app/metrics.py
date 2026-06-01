"""Prometheus metrics for IEP2 (vision).

Uses a private registry so importing/re-importing never collides with the global
default registry, and the worker can expose exactly these on /metrics. Includes
the project-mandated ML signal (detection confidence distribution).
"""

from __future__ import annotations

try:
    from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, start_http_server
except ModuleNotFoundError:  # pragma: no cover - only used on lightweight hosts
    class _NoopMetric:
        def labels(self, *args, **kwargs):
            return self

        def observe(self, *args, **kwargs):
            return None

        def inc(self, *args, **kwargs):
            return None

        def set(self, *args, **kwargs):
            return None

    class CollectorRegistry:
        pass

    def Counter(*args, **kwargs):
        return _NoopMetric()

    def Gauge(*args, **kwargs):
        return _NoopMetric()

    def Histogram(*args, **kwargs):
        return _NoopMetric()

    def start_http_server(*args, **kwargs):
        return None

REGISTRY = CollectorRegistry()

frame_latency = Histogram(
    "iep2_frame_processing_seconds", "Per-frame pipeline latency", ["camera_id"], registry=REGISTRY
)
detections_per_frame = Histogram(
    "iep2_detections_per_frame", "Detection count per frame", ["camera_id"], registry=REGISTRY
)
reid_resolutions = Counter(
    "iep2_reid_resolutions_total", "ReID resolution outcomes", ["camera_id", "outcome"], registry=REGISTRY
)
active_tracks = Gauge("iep2_active_tracks", "Active tracks", ["camera_id"], registry=REGISTRY)
lost_pool_size = Gauge("iep2_lost_pool_size", "Lost pool size", ["camera_id"], registry=REGISTRY)
# ML signal: detection confidence distribution
detection_confidence = Histogram(
    "iep2_detection_confidence", "YOLO confidence distribution", ["camera_id"], registry=REGISTRY
)


def start_metrics_server(port: int) -> None:
    """Expose the IEP2 metrics registry on ``port`` (/metrics)."""
    start_http_server(port, registry=REGISTRY)
