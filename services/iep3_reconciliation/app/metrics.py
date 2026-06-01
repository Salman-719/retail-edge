"""Prometheus metrics for IEP3 (reconciliation).

Private registry; the project-mandated ML signal here is the cross-camera match
similarity distribution.
"""

from __future__ import annotations

try:
    from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, start_http_server
except ModuleNotFoundError:  # pragma: no cover - only used on lightweight hosts
    class _NoopMetric:
        def labels(self, *args, **kwargs):
            return self

        def observe(self, *args, **kwargs):
            return None

        def inc(self, *args, **kwargs):
            return None

        def set(self, *args, **kwargs):
            return None

    class CollectorRegistry:
        pass

    def Counter(*args, **kwargs):
        return _NoopMetric()

    def Gauge(*args, **kwargs):
        return _NoopMetric()

    def Histogram(*args, **kwargs):
        return _NoopMetric()

    def start_http_server(*args, **kwargs):
        return None

REGISTRY = CollectorRegistry()

reconcile_latency = Histogram(
    "iep3_batch_reconcile_seconds", "Per-batch reconcile time", registry=REGISTRY
)
global_links = Counter(
    "iep3_global_links_total", "Linking outcomes", ["outcome"], registry=REGISTRY
)  # new_global | cross_camera | reactivated
active_globals = Gauge("iep3_active_global_ids", "Active GlobalIDs", registry=REGISTRY)
positions_written = Counter(
    "iep3_positions_written_total", "Canonical positions written", registry=REGISTRY
)
# ML signal: cross-camera match similarity distribution
match_similarity = Histogram(
    "iep3_cross_camera_similarity", "Cosine similarity of accepted cross-camera matches",
    registry=REGISTRY,
)


def start_metrics_server(port: int) -> None:
    """Expose the IEP3 metrics registry on ``port`` (/metrics)."""
    start_http_server(port, registry=REGISTRY)
