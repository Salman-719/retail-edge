"""Prometheus metrics for the IEP2 per-camera vision daemon."""
from __future__ import annotations

import os

from prometheus_client import Counter, Gauge, Histogram, start_http_server

MODEL_VERSION = os.environ.get("MODEL_VERSION", "production")

IEP2_FRAMES = Counter(
    "iep2_frames_processed_total",
    "Total frames processed by IEP2",
    ["camera_id"],
)

IEP2_FRAME_LATENCY = Histogram(
    "iep2_frame_latency_seconds",
    "End-to-end frame processing latency in IEP2",
    ["camera_id"],
    buckets=[0.01, 0.025, 0.05, 0.1, 0.2, 0.5, 1.0, 2.0, 5.0, 10.0],
)

IEP2_ERRORS = Counter(
    "iep2_processing_errors_total",
    "IEP2 frame or batch processing errors",
    ["camera_id"],
)

IEP2_DETECTIONS_PER_FRAME = Histogram(
    "iep2_detections_per_frame",
    "Person detections per processed frame",
    ["camera_id"],
    buckets=[0, 1, 2, 3, 5, 8, 12, 20, 30, 50],
)

IEP2_DETECTION_CONFIDENCE = Histogram(
    "iep2_detection_confidence",
    "YOLO person detection confidence observed by IEP2",
    ["camera_id", "model_version"],
    buckets=[0.25, 0.30, 0.35, 0.40, 0.50, 0.60, 0.70, 0.80, 0.90, 1.0],
)

IEP2_TRACKS_ACTIVE = Gauge(
    "iep2_tracks_active",
    "Confirmed/pending tracker outputs in the most recent frame",
    ["camera_id"],
)

IEP2_TRACK_AGE = Histogram(
    "iep2_track_age_frames",
    "Number of frames seen for a local track",
    ["camera_id", "model_version"],
    buckets=[1, 2, 3, 5, 10, 20, 50, 100, 200],
)

IEP2_IDENTITY_SWITCHES = Counter(
    "iep2_identity_switches_total",
    "New local tracks created after the first frame of a camera stream",
    ["camera_id"],
)


def start_metrics_server(port: int = 9201) -> None:
    start_http_server(port)
