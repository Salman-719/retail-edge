"""Prometheus metrics for the IEP1 edge ingestion daemon."""
from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram, start_http_server

IEP1_FRAMES = Counter(
    "iep1_frames_captured_total",
    "Total frames captured and accepted into IEP1 windows",
    ["camera_id"],
)

IEP1_FRAMES_DROPPED = Counter(
    "iep1_frames_dropped_total",
    "Frames dropped before windowing",
    ["camera_id"],
)

IEP1_ENCODE_ERRORS = Counter(
    "iep1_encode_errors_total",
    "Frames that failed JPEG encoding or tmpfs write",
    ["camera_id"],
)

IEP1_ACTIVE_CAMERAS = Gauge(
    "iep1_active_cameras",
    "Number of cameras currently captured by this IEP1 daemon",
)

IEP1_PUBLISH_LATENCY = Histogram(
    "iep1_manifest_publish_seconds",
    "Time to publish one IEP1 window manifest to local Redis",
    buckets=[0.0005, 0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0],
)


def start_metrics_server(port: int = 9200) -> None:
    start_http_server(port)
