"""Shared fixtures for EEP unit tests.

Adds the EEP service and the mlops directory to sys.path so imports resolve
without a pip install of either package.

Stubs out heavy optional dependencies (prometheus_client, mlflow, fastapi,
starlette) so unit tests run in the bare Python environment used in CI.
"""
import sys
import os
from types import ModuleType
from unittest.mock import MagicMock

# EEP service root — makes `from app.core.shadow import ...` work.
sys.path.insert(
    0,
    os.path.join(os.path.dirname(__file__), "..", "..", "..",
                 "services", "eep"),
)

# mlops root — makes `import compare_shadow` and `import canary_eval` work.
sys.path.insert(
    0,
    os.path.join(os.path.dirname(__file__), "..", "..", "..",
                 "mlops"),
)

# ── prometheus_client stub ────────────────────────────────────────────────────
# The real package is not installed in the unit-test environment.
# We need Counter/Gauge/Histogram to be real enough that:
#   - Counter(name, help, labelnames) constructs without error
#   - .labels(**kw) returns a child with ._labelnames, ._value.get(), .inc(), .observe(), .set()
#   - ._labelnames on the parent counter is inspectable

class _FakeChild:
    def __init__(self):
        self._val = 0.0

    def get(self):
        return self._val

    def inc(self, amount=1):
        self._val += amount

    def observe(self, amount):
        self._val += amount

    def set(self, value):
        self._val = value


class _FakeMetric:
    def __init__(self, name, help, labelnames=None, buckets=None):
        self._name = name
        self._labelnames = tuple(labelnames or [])
        self._children = {}
        # For label-free metrics, expose a single child directly.
        self._child = _FakeChild()

    def labels(self, **kw):
        key = tuple(sorted(kw.items()))
        if key not in self._children:
            self._children[key] = _FakeChild()
        return self._children[key]

    # Label-free convenience (used by metrics without labelnames).
    def inc(self, amount=1):
        self._child.inc(amount)

    def observe(self, amount):
        self._child.observe(amount)

    def set(self, value):
        self._child.set(value)

    @property
    def _value(self):
        return self._child


def _make_fake_prometheus():
    mod = ModuleType("prometheus_client")
    mod.Counter   = _FakeMetric
    mod.Gauge     = _FakeMetric
    mod.Histogram = _FakeMetric
    mod.start_http_server = lambda port: None
    return mod


if "prometheus_client" not in sys.modules:
    sys.modules["prometheus_client"] = _make_fake_prometheus()

# ── fastapi / starlette stub ──────────────────────────────────────────────────
# canary.py imports Request, BaseHTTPMiddleware, ASGIApp.

if "fastapi" not in sys.modules:
    fastapi_mod = ModuleType("fastapi")
    fastapi_mod.Request = MagicMock
    sys.modules["fastapi"] = fastapi_mod

if "starlette" not in sys.modules:
    starlette_mod = ModuleType("starlette")
    sys.modules["starlette"] = starlette_mod

for _sub in ("starlette.middleware", "starlette.middleware.base", "starlette.types"):
    if _sub not in sys.modules:
        _m = ModuleType(_sub)
        if _sub == "starlette.middleware.base":
            _m.BaseHTTPMiddleware = object  # canary inherits from this
        if _sub == "starlette.types":
            _m.ASGIApp = object
        sys.modules[_sub] = _m

# ── mlflow stub ───────────────────────────────────────────────────────────────
# canary_eval.py imports mlflow lazily (inside functions), but the test env
# may not have it. We inject a stub so the lazy import succeeds.

if "mlflow" not in sys.modules:
    mlflow_mod = ModuleType("mlflow")
    mlflow_mod.set_tracking_uri = MagicMock()
    mlflow_mod.set_experiment   = MagicMock()
    mlflow_mod.start_run        = MagicMock()
    mlflow_mod.log_params       = MagicMock()
    mlflow_mod.log_metric       = MagicMock()
    mlflow_mod.log_param        = MagicMock()
    tracking_mod = ModuleType("mlflow.tracking")
    tracking_mod.MlflowClient = MagicMock()
    mlflow_mod.tracking = tracking_mod
    sys.modules["mlflow"]          = mlflow_mod
    sys.modules["mlflow.tracking"] = tracking_mod
