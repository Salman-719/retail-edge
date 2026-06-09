"""Prometheus metrics for IEP3 reconciliation.

IEP3 is a portless asyncio daemon, so we expose metrics via a side HTTP server
(prometheus_client.start_http_server) on :9300. Prometheus scrapes job "iep3"
(see monitoring/prometheus.yml).

Metric objects are defined ONCE at module import time — re-defining the same
name raises a duplicate-timeseries error. The reconciler imports and updates
these inline on the real batch hot path; main.py starts the HTTP server.
"""
from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram, start_http_server

IEP3_ERRORS = Counter(
    "iep3_errors_total",
    "Reconciliation errors by type",
    ["error_type"],
)

# How many reconciliation batches IEP3 has fully processed.
IEP3_BATCHES = Counter(
    "iep3_batches_processed_total",
    "Reconciliation batches processed",
)

# Wall-clock time to reconcile one batch (the whole process_batch transaction).
IEP3_RECONCILE = Histogram(
    "iep3_batch_reconcile_seconds",
    "Time to reconcile one batch",
)

# LocalIDs matched to an already-known global identity in this batch
# (cross-camera / re-appearance recovery).
IEP3_MATCHES = Counter(
    "iep3_reid_matches_total",
    "LocalIDs matched to an existing global identity",
)

# Brand-new global identities created this batch (no prior match).
IEP3_NEW = Counter(
    "iep3_reid_new_identities_total",
    "New global identities created",
)

# Identity state-machine transitions per batch, split by transition type.
# Bounded label set: only "lost" and "exited" are ever used.
IEP3_TRANSITIONS = Counter(
    "iep3_identity_transitions_total",
    "Global identity state-machine transitions",
    ["transition"],
)

IEP3_CAMERAS_REPORTING = Histogram(
    "iep3_batch_cameras_reporting",
    "Number of cameras that reported before reconciliation fired",
    buckets=[1, 2, 3, 4, 5, 6, 8, 10, 16, 24, 32],
)

IEP3_REID_COSINE = Histogram(
    "iep3_reid_cosine_similarity",
    "Cosine similarity observed by the appearance fallback matcher",
    buckets=[0.30, 0.40, 0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.90, 1.0],
)

IEP3_REID_MATCH_RATE = Gauge(
    "iep3_reid_match_rate",
    "Fraction of local identities linked cross-camera in the last batch",
)


def start_metrics_server(port: int = 9300) -> None:
    """Start the /metrics HTTP server on its own background thread.

    Safe to call once at daemon startup; does not interfere with the asyncio
    event loop. Raises if the port is already bound.
    """
    start_http_server(port)
