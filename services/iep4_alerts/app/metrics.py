"""Prometheus metrics for the IEP4 alerts daemon.

IEP4 is a portless long-running asyncio daemon — one process per store — so
metrics are exposed via a side HTTP server (prometheus_client.start_http_server)
on :8004, the same pattern as IEP1 (:9200) and IEP2 (:9201). Prometheus scrapes
job "iep4" (see monitoring/prometheus.yml). The store is identified by the scrape
target/instance, so metrics carry no store_id label (it would be constant per
process); only within-process dimensions (rule_type, email outcome) are labelled.

Metric objects are defined once at import. daemon.py / cooldown.py / delivery.py
update them on the evaluation path; main.py starts the server.
"""
from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram, start_http_server

# Evaluation-cycle liveness. rate(iep4_cycles_total) == 0 means the daemon stalled.
IEP4_CYCLES = Counter(
    "iep4_cycles_total",
    "Evaluation cycles executed by the IEP4 daemon",
)
IEP4_CYCLE_SECONDS = Histogram(
    "iep4_cycle_seconds",
    "Wall-clock duration of one IEP4 evaluation cycle",
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
)
IEP4_CYCLE_ERRORS = Counter(
    "iep4_cycle_errors_total",
    "Evaluation cycles that raised and were skipped",
)

# Per-window throughput — drives the alerts-pipeline dashboard.
IEP4_ZONE_TRANSITIONS = Counter(
    "iep4_zone_transitions_total",
    "Zone transitions recorded across all evaluated windows",
)
IEP4_VISITS_OPENED = Counter(
    "iep4_visits_opened_total",
    "Visit sessions opened for first-seen persons",
)
IEP4_VISITS_CLOSED = Counter(
    "iep4_visits_closed_total",
    "Visit sessions closed when IEP3 marked the person LOST/EXITED",
)
IEP4_ACTIVE_PERSONS = Gauge(
    "iep4_active_persons",
    "Persons currently held in active_person_state by this IEP4 instance",
)

# Alerts fired, by rule type (queue_buildup, staff_zone, ...). A spike is the
# signal operators actually care about.
IEP4_ALERTS_FIRED = Counter(
    "iep4_alerts_fired_total",
    "Alerts fired by the cooldown state machine",
    ["rule_type"],
)

# Alert email delivery outcomes. outcome = sent | failed.
IEP4_EMAILS = Counter(
    "iep4_emails_total",
    "Alert email delivery attempts by outcome",
    ["outcome"],
)


def start_metrics_server(port: int = 8004) -> None:
    """Start the /metrics HTTP server on its own background thread.

    Safe to call once at daemon startup; does not interfere with the asyncio
    event loop. Raises if the port is already bound.
    """
    start_http_server(port)
