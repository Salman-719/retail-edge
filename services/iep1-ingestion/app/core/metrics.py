"""Prometheus metrics for IEP1-ingestion."""
from prometheus_client import Counter, Histogram

video_uploads = Counter(
    "iep1_video_uploads_total",
    "Total video uploads processed",
    ["status"],  # success | error
)

video_upload_bytes = Counter(
    "iep1_video_upload_bytes_total",
    "Total bytes of video uploaded to S3",
)

video_duration_seconds = Histogram(
    "iep1_video_duration_seconds",
    "Duration of uploaded videos in seconds",
    buckets=[10, 30, 60, 120, 300, 600, 1800, 3600],
)

frame_extraction_duration = Histogram(
    "iep1_frame_extraction_duration_seconds",
    "Time to extract a single frame from stored video",
    buckets=[0.1, 0.25, 0.5, 1, 2, 5],
)
