"""Prometheus metrics for IEP1 ingestion daemon.

IEP1 is a portless asyncio daemon, so metrics are exposed via a side HTTP
server (prometheus_client.start_http_server) on :9200. Prometheus scrapes
job "iep1" — see monitoring/prometheus.yml.

Metric objects are defined once at module import time. The worker and daemon
modules import and update these on the hot path. main.py starts the server.
"""
from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram, start_http_server

# Total frames captured across all cameras. The rate of this counter is
# the primary pipeline liveness signal — rate == 0 means nothing is flowing.
IEP1_FRAMES = Counter(
    "iep1_frames_captured_total",
    "Total frames captured and written to tmpfs",
    ["camera_id"],
)

# Frames dropped because the asyncio queue between capture thread and window
# manager was full. Sustained drops mean the event loop is falling behind.
IEP1_FRAMES_DROPPED = Counter(
    "iep1_frames_dropped_total",
    "Frames dropped due to full inter-thread queue",
    ["camera_id"],
)

# Frames that failed to encode as JPEG or write to tmpfs.
IEP1_ENCODE_ERRORS = Counter(
    "iep1_encode_errors_total",
    "Frames that failed JPEG encoding or tmpfs write",
    ["camera_id"],
)

# How many cameras IEP1 is currently streaming. Driven by AddCamera/RemoveCamera.
IEP1_ACTIVE_CAMERAS = Gauge(
    "iep1_active_cameras",
    "Number of cameras currently being captured by IEP1",
)

# Time to publish one window manifest to Redis (XADD latency).
# Spikes here indicate edge-local Redis is under pressure.
IEP1_PUBLISH_LATENCY = Histogram(
    "iep1_manifest_publish_seconds",
    "Time to XADD one window manifest to the local Redis stream",
    buckets=[0.0005, 0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25],
)

# Backpressure: frames dropped because IEP1's cgroup memory (which includes the
# tmpfs frame pages it writes) crossed the high watermark. A non-zero rate means
# IEP2 is falling behind and IEP1 is shedding load to stay alive instead of
# OOM-killing — windows degrade gracefully rather than the pipeline dying.
IEP1_BACKPRESSURE_DROPS = Counter(
    "iep1_backpressure_drops_total",
    "Frames dropped by memory backpressure (IEP2 falling behind)",
    ["camera_id"],
)

# 1 while backpressure is engaged, 0 otherwise (hysteresis between low/high marks).
IEP1_BACKPRESSURE_ENGAGED = Gauge(
    "iep1_backpressure_engaged",
    "1 when IEP1 is shedding frames due to memory pressure, else 0",
)

# IEP1 cgroup memory utilisation fraction (current/limit), updated each check.
IEP1_MEMORY_FRACTION = Gauge(
    "iep1_memory_fraction",
    "IEP1 container memory usage as a fraction of its cgroup limit",
)


def start_metrics_server(port: int = 9200) -> None:
    """Start the /metrics HTTP server on its own background thread.

    Safe to call once at daemon startup; does not interfere with the asyncio
    event loop. Idempotent: if the port is already bound (main.py and run_daemon
    both call this), the existing server keeps serving and we no-op.
    """
    try:
        start_http_server(port)
    except OSError:
        pass
