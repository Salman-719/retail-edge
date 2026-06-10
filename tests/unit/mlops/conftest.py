"""Shared fixtures for mlops unit tests.

Adds the mlops directory to sys.path and stubs heavy optional dependencies
(mlflow) so tests run without a live MLflow server or a pip install.
"""
from __future__ import annotations

import sys
import os
from types import ModuleType
from unittest.mock import MagicMock

# mlops root — makes `import promote`, `import run_promotion`, `import check_state` work.
_MLOPS_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "..", "mlops")
if _MLOPS_DIR not in sys.path:
    sys.path.insert(0, _MLOPS_DIR)


# ── mlflow stub ───────────────────────────────────────────────────────────────
# promote.py and run_promotion.py import mlflow lazily (inside functions).
# check_state.py also imports lazily. We inject a usable stub so every test
# can control the client's return values without a live server.

def _make_mlflow_stub():
    mod = ModuleType("mlflow")
    mod.set_tracking_uri = MagicMock()
    mod.set_experiment   = MagicMock()
    mod.log_params       = MagicMock()
    mod.log_metrics      = MagicMock()
    mod.log_param        = MagicMock()
    mod.log_metric       = MagicMock()
    mod.set_tags         = MagicMock()

    # start_run returns a context manager whose .info.run_id is accessible.
    run_info      = MagicMock()
    run_info.run_id = "test-run-id"
    run_ctx       = MagicMock()
    run_ctx.__enter__ = MagicMock(return_value=run_info)
    run_ctx.__exit__  = MagicMock(return_value=False)
    mod.start_run = MagicMock(return_value=run_ctx)

    tracking_mod  = ModuleType("mlflow.tracking")
    tracking_mod.MlflowClient = MagicMock()
    mod.tracking  = tracking_mod

    return mod, tracking_mod


if "mlflow" not in sys.modules:
    _mlflow_stub, _tracking_stub = _make_mlflow_stub()
    sys.modules["mlflow"]          = _mlflow_stub
    sys.modules["mlflow.tracking"] = _tracking_stub
