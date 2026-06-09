"""IEP5 Pushgateway metrics tests.

IEP5 is a one-shot job, so its metrics are PUSHED to a Pushgateway at job end.
These verify: the push is a no-op without a configured gateway, it pushes with
the right job + grouping key when configured, and a gateway failure never
propagates into the job (the exit code must reflect the analytics result, not
a metrics hiccup).

metrics.py only imports prometheus_client (no `app.*`), so we load it by file
path to avoid the cross-service `app` package-name collision.
"""
import importlib.util
from pathlib import Path

_METRICS = (
    Path(__file__).resolve().parents[3]
    / "services" / "iep5_analytics" / "app" / "metrics.py"
)


def _load():
    spec = importlib.util.spec_from_file_location("iep5_metrics_under_test", _METRICS)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_push_skips_without_gateway(monkeypatch):
    m = _load()
    calls = []
    monkeypatch.setattr(m, "push_to_gateway", lambda *a, **k: calls.append(k))
    monkeypatch.delenv("IEP5_PUSHGATEWAY_URL", raising=False)

    m.push_metrics("store1", "2026-06-09")

    assert calls == []  # no gateway configured → no push


def test_push_calls_gateway_with_grouping(monkeypatch):
    m = _load()
    calls = []
    monkeypatch.setattr(m, "push_to_gateway", lambda gw, **k: calls.append((gw, k)))
    monkeypatch.setenv("IEP5_PUSHGATEWAY_URL", "pushgateway:9091")

    m.push_metrics("store1", "2026-06-09")

    assert len(calls) == 1
    gateway, kwargs = calls[0]
    assert gateway == "pushgateway:9091"
    assert kwargs["job"] == "iep5"
    assert kwargs["grouping_key"] == {"store_id": "store1", "shift_date": "2026-06-09"}
    assert kwargs["registry"] is m.REGISTRY


def test_push_never_raises_on_gateway_error(monkeypatch):
    m = _load()

    def _boom(*a, **k):
        raise RuntimeError("gateway unreachable")

    monkeypatch.setattr(m, "push_to_gateway", _boom)
    monkeypatch.setenv("IEP5_PUSHGATEWAY_URL", "pushgateway:9091")

    # Must swallow — a metrics push failure cannot change the job's exit code.
    m.push_metrics("store1", "2026-06-09")
