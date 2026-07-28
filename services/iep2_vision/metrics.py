"""Prometheus metrics for IEP2 vision daemon.

IEP2 is a portless asyncio daemon in production, so metrics are exposed via
a side HTTP server (prometheus_client.start_http_server) on :9201.
Prometheus scrapes job "iep2" — see monitoring/prometheus.yml.

In the k3s production deployment each IEP2 pod is annotated for discovery:
  prometheus.io/scrape: "true"
  prometheus.io/port: "9201"

Metric objects are defined once at module import time. runtime.py imports
and updates these on the per-frame hot path. main.py starts the server.
"""
from __future__ import annotations

import os

from prometheus_client import Counter, Gauge, Histogram, start_http_server

# Set at container startup from MODEL_VERSION env var (default "production").
# A canary deployment sets MODEL_VERSION=canary so Prometheus automatically
# separates production and canary time-series for ML-signal metrics.
_MODEL_VERSION = os.environ.get("MODEL_VERSION", "production")
# Public alias: runtime.py / detector.py / reid.py import `MODEL_VERSION`. Keep both
# names in sync so those imports resolve (the rename left them referencing the
# un-prefixed name, which crashed IEP2 on import).
MODEL_VERSION = _MODEL_VERSION

# Total frames processed by this IEP2 instance. Rate == 0 means the pipeline
# has stalled for this camera.
IEP2_FRAMES = Counter(
    "iep2_frames_processed_total",
    "Total frames processed by this IEP2 instance",
    ["camera_id"],
)

# End-to-end per-frame latency: from receiving the frame to writing DB rows.
# This is the primary latency budget for the vision pipeline.
IEP2_FRAME_LATENCY = Histogram(
    "iep2_frame_latency_seconds",
    "End-to-end time from frame receipt to tracking_history write",
    ["camera_id"],
    buckets=[0.01, 0.025, 0.05, 0.1, 0.2, 0.5, 1.0, 2.0, 5.0],
)

# Errors during DB writes or pipeline processing.
IEP2_ERRORS = Counter(
    "iep2_processing_errors_total",
    "Frames that caused an unhandled error during tracking or DB write",
    ["camera_id"],
)

# Number of detections returned by YOLO per frame.
# Sudden sustained drop to 0 across frames means YOLO stopped detecting
# people — could be model stall, empty scene, or ZMQ socket failure.
IEP2_DETECTIONS_PER_FRAME = Histogram(
    "iep2_detections_per_frame",
    "Number of person detections returned by YOLO for each frame",
    ["camera_id"],
    buckets=[0, 1, 2, 3, 5, 8, 12, 20, 30],
)

# ML signal: per-detection confidence score distribution per camera.
# Tracks model certainty over time for this specific camera's scene.
# Drift toward lower buckets signals degraded camera quality (dirty lens,
# lighting shift, camera repositioning) before detection count drops.
IEP2_DETECTION_CONFIDENCE = Histogram(
    "iep2_detection_confidence",
    "Confidence score of each YOLO person detection per camera (ML signal)",
    ["camera_id", "model_version"],
    buckets=[0.25, 0.30, 0.35, 0.40, 0.50, 0.60, 0.70, 0.80, 0.90, 1.0],
)

# ML signal: how many frames a track survives before being dropped by BoTSORT.
# Very short track lifetimes (1–2 frames) indicate the tracker cannot maintain
# identity through occlusion — a model performance signal distinct from
# detection count. Measured at track termination, not per-frame.
IEP2_TRACK_AGE = Histogram(
    "iep2_track_age_frames",
    "Number of frames a BoTSORT track survived before being dropped (ML signal)",
    ["camera_id", "model_version"],
    buckets=[1, 2, 3, 5, 10, 20, 50, 100, 200],
)

# Instantaneous count of active BoTSORT tracks per camera per frame.
# Drives the tracker lifecycle dashboard "active tracks over time" panel.
IEP2_TRACKS_ACTIVE = Gauge(
    "iep2_tracks_active",
    "Number of confirmed BoTSORT tracks active in the most recent frame",
    ["camera_id"],
)

# Total identity switches (track ID reassignment events). Incremented each time
# BoTSORT assigns a new local_id to a detection that was already tracking —
# a proxy for tracker fragmentation / occlusion-handling quality.
IEP2_IDENTITY_SWITCHES = Counter(
    "iep2_identity_switches_total",
    "Number of times BoTSORT dropped and re-acquired the same physical person",
    ["camera_id"],
)

# Inference requests (YOLO detect / ReID extract) that exceeded their per-request
# deadline and fell back to an empty result. A sustained non-zero rate means the
# shared yolo/reid service is wedged or overloaded — the pipeline degrades to
# empty-but-advancing frames instead of hanging the camera forever.
IEP2_INFERENCE_TIMEOUTS = Counter(
    "iep2_inference_timeouts_total",
    "Inference requests that exceeded their deadline and returned a fallback",
    ["camera_id", "service"],  # service = "yolo" | "reid"
)

# ── Per-window phase breakdown ────────────────────────────────────────────────
# IEP2 must finish a window in less than the window duration; if it does not, the
# backlog is permanent (manifests are consumed oldest-first with no skip-ahead),
# the camera falls behind its peers, and IEP3 stops reconciling them together.
# Until now only two coarse numbers were logged — a residual YOLO await and a
# lumped tracker figure — which together accounted for ~48s of a measured ~65s
# window, leaving ~17s unattributed. Everything outside those two (live publish,
# row building, per-frame metrics, the DB writes, batch_complete, cleanup) was
# invisible. Seconds are accumulated per phase across the window and observed
# ONCE at batch close, so the instrumentation itself costs ~nothing per frame.
IEP2_PHASE_SECONDS = Histogram(
    "iep2_phase_seconds",
    "Wall time spent in one pipeline phase over a single window",
    ["camera_id", "phase"],
    buckets=[0.01, 0.05, 0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 20.0, 40.0, 60.0],
)

# Total wall time for one window, end to end. Compare against the sum of
# IEP2_PHASE_SECONDS to prove the breakdown is complete: a growing residual means
# time is being spent somewhere still uninstrumented. Values at or above the
# window duration mean this camera cannot keep up and is accumulating lag.
IEP2_WINDOW_WALL_SECONDS = Histogram(
    "iep2_window_wall_seconds",
    "End-to-end wall time to process one window",
    ["camera_id"],
    buckets=[10, 20, 30, 40, 50, 55, 60, 65, 70, 80, 100, 150],
)


def start_metrics_server(port: int = 9201) -> None:
    """Start the /metrics HTTP server on its own background thread.

    Safe to call once at daemon startup; does not interfere with the asyncio
    event loop. Raises if the port is already bound.
    """
    start_http_server(port)
