"""Prometheus metrics for the IEP5 end-of-shift analytics Job.

IEP5 is a one-shot Job that runs to completion and exits — it is NOT a standing
scrape target (unlike the IEP1/IEP2/IEP4 daemons, which run start_http_server).
A process that lives seconds cannot be reliably scraped, so IEP5 PUSHES its
metrics to a Prometheus Pushgateway at job end (the standard batch-job pattern);
Prometheus scrapes the gateway. Each push is grouped by (store_id, shift_date),
so a re-run of the same shift overwrites the previous run's series rather than
accumulating duplicates.

All metrics live in a dedicated CollectorRegistry so only IEP5 series are pushed.
"""
from __future__ import annotations

import logging
import os

from prometheus_client import CollectorRegistry, Gauge, push_to_gateway

logger = logging.getLogger("iep5.metrics")

REGISTRY = CollectorRegistry()

# Wall-clock duration of the whole job. Drives the "analytics job runtime" panel
# and catches a job that is creeping toward its k8s activeDeadline.
IEP5_JOB_DURATION = Gauge(
    "iep5_job_duration_seconds",
    "Wall-clock duration of the IEP5 analytics job",
    registry=REGISTRY,
)
# 1 = success (or idempotent already-done / empty shift), 0 = preflight failure
# or error. Alert on iep5_job_success == 0.
IEP5_JOB_SUCCESS = Gauge(
    "iep5_job_success",
    "1 if the IEP5 job completed successfully, 0 otherwise",
    registry=REGISTRY,
)
# global_tracking_history rows in the shift window aggregated by this run. 0 is a
# valid empty shift; a sustained 0 across stores signals an upstream pipeline gap.
IEP5_GTH_ROWS = Gauge(
    "iep5_gth_rows_processed",
    "global_tracking_history rows in the shift window aggregated by this run",
    registry=REGISTRY,
)
# Unix time of the last successful completion — drives a staleness alert
# ("no successful IEP5 for store X in 24h").
IEP5_LAST_SUCCESS_TIMESTAMP = Gauge(
    "iep5_last_success_timestamp_seconds",
    "Unix time of the last successful IEP5 completion",
    registry=REGISTRY,
)


def push_metrics(store_id: str, shift_date: str) -> None:
    """Push the IEP5 registry to the Pushgateway, grouped by (store, date).

    No-op when IEP5_PUSHGATEWAY_URL is unset (dev without a gateway). NEVER
    raises into the job — a metrics push failure must not change the exit code
    or mask the real result.
    """
    gateway = os.environ.get("IEP5_PUSHGATEWAY_URL", "").strip()
    if not gateway:
        logger.info("IEP5_PUSHGATEWAY_URL unset — skipping metrics push")
        return
    try:
        push_to_gateway(
            gateway,
            job="iep5",
            grouping_key={"store_id": str(store_id), "shift_date": str(shift_date)},
            registry=REGISTRY,
        )
        logger.info("Pushed IEP5 metrics to %s (store=%s date=%s)", gateway, store_id, shift_date)
    except Exception:
        logger.exception("IEP5 metrics push failed — continuing (exit code unaffected)")
