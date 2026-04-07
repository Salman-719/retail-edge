"""Prometheus metrics for EEP.

HTTP metrics are auto-instrumented via prometheus-fastapi-instrumentator.
Business metrics are defined here and imported where needed.
"""
from prometheus_client import Counter, Histogram

# ── Calibration ───────────────────────────────────────────────────────────────

calibration_attempts = Counter(
    "eep_calibration_attempts_total",
    "Total homography calibration attempts",
    ["status"],  # ok | rejected | failed
)

# ── Floor plan ────────────────────────────────────────────────────────────────

floor_plan_uploads = Counter(
    "eep_floor_plan_uploads_total",
    "Total floor plan uploads",
    ["format"],  # png | jpg | pdf
)

# ── Proxy latency to IEPs ─────────────────────────────────────────────────────

iep_proxy_duration = Histogram(
    "eep_iep_proxy_duration_seconds",
    "Time EEP waits for an IEP response",
    ["iep", "operation"],  # e.g. iep1/video_upload, iep2/tracking_start
    buckets=[0.1, 0.5, 1, 2, 5, 10, 30, 60],
)
