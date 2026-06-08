"""Prometheus metrics for IEP3 reconciliation.

IEP3 is a portless asyncio daemon, so we expose metrics via a side HTTP server
(prometheus_client.start_http_server) on :9300. Prometheus scrapes job "iep3"
(see monitoring/prometheus.yml).

Metric objects are defined ONCE at module import time — re-defining the same
name raises a duplicate-timeseries error. The reconciler imports and updates
these inline on the real batch hot path; main.py starts the HTTP server.
"""
from __future__ import annotations

from prometheus_client import Counter, Histogram, start_http_server

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


def start_metrics_server(port: int = 9300) -> None:
    """Start the /metrics HTTP server on its own background thread.

    Safe to call once at daemon startup; does not interfere with the asyncio
    event loop. Raises if the port is already bound.
    """
    start_http_server(port)
