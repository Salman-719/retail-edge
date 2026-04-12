"""Prometheus metrics for IEP2-vision."""
from prometheus_client import Counter, Histogram, Gauge

tracking_jobs = Counter(
    "iep2_tracking_jobs_total",
    "Total tracking jobs completed",
    ["status"],  # done | error
)

tracking_job_duration = Histogram(
    "iep2_tracking_job_duration_seconds",
    "End-to-end duration of a YOLO+ByteTrack tracking job",
    buckets=[10, 30, 60, 120, 300, 600, 1800],
)

tracking_frames_processed = Counter(
    "iep2_tracking_frames_processed_total",
    "Total video frames processed by YOLO",
)

tracking_detections = Counter(
    "iep2_tracking_detections_total",
    "Total person detections across all tracking jobs",
)

heatmap_generation_duration = Histogram(
    "iep2_heatmap_generation_duration_seconds",
    "Time to generate and upload a heatmap",
    buckets=[0.1, 0.5, 1, 2, 5, 10],
)

active_tracking_jobs = Gauge(
    "iep2_active_tracking_jobs",
    "Number of tracking jobs currently running",
)
