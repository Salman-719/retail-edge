"""Unit tests for Stage 3 canary traffic splitting.

Test groups
-----------
1. Splitter distribution — assign_model_version() distributes correctly.
2. model_version label — EEP_REQUESTS counter carries the label.
3. Canary eval — pass/fail from mocked Prometheus metric values.
4. Rollback trigger — rollback() writes .env.canary and calls MLflow.
"""
from __future__ import annotations

import os
import sys
import tempfile
import importlib
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fresh_canary_module():
    """Re-import canary with a clean Prometheus registry each time.

    prometheus_client raises ValueError if the same metric name is registered
    twice in the same process. We work around this by deleting the module from
    sys.modules so the Counter/Histogram constructor runs again on a fresh
    CollectorRegistry in each test that needs isolation.
    """
    for mod in list(sys.modules):
        if mod in ("app.core.canary", "canary_eval"):
            del sys.modules[mod]
    return None


# ── Group 1: Splitter distribution ────────────────────────────────────────────

class TestAssignModelVersion:
    """Pure function: canary_percentage controls routing; 0 is always production."""

    def test_zero_percent_always_production(self):
        from app.core.canary import assign_model_version
        for rand in [0.0, 0.01, 0.5, 0.99, 1.0]:
            assert assign_model_version(0, rand_value=rand) == "production"

    def test_zero_percent_does_not_call_random(self):
        """When pct==0, random.random() must never be invoked."""
        from app.core.canary import assign_model_version
        with patch("app.core.canary.random.random", side_effect=AssertionError("should not be called")):
            result = assign_model_version(0)
        assert result == "production"

    def test_hundred_percent_always_canary(self):
        from app.core.canary import assign_model_version
        for rand in [0.0, 0.5, 0.99]:
            assert assign_model_version(100, rand_value=rand) == "canary"

    def test_threshold_boundary_below(self):
        """rand < pct/100 → canary."""
        from app.core.canary import assign_model_version
        # 10% canary: rand=0.099 < 0.10 → canary
        assert assign_model_version(10, rand_value=0.099) == "canary"

    def test_threshold_boundary_above(self):
        """rand >= pct/100 → production."""
        from app.core.canary import assign_model_version
        # 10% canary: rand=0.10 >= 0.10 → production
        assert assign_model_version(10, rand_value=0.10) == "production"

    def test_statistical_distribution(self):
        """50% canary setting should route ~50% of requests to canary.

        Uses 10 000 samples; accepts ±5% tolerance (well within 6σ for p=0.5).
        """
        from app.core.canary import assign_model_version
        import random as _random

        rng = _random.Random(42)
        n = 10_000
        canary_count = sum(
            1 for _ in range(n) if assign_model_version(50, rand_value=rng.random()) == "canary"
        )
        ratio = canary_count / n
        assert 0.45 <= ratio <= 0.55, f"Expected ~0.50, got {ratio:.4f}"

    def test_statistical_distribution_10pct(self):
        """10% canary setting should route ~10% to canary (±5% tolerance)."""
        from app.core.canary import assign_model_version
        import random as _random

        rng = _random.Random(7)
        n = 10_000
        canary_count = sum(
            1 for _ in range(n) if assign_model_version(10, rand_value=rng.random()) == "canary"
        )
        ratio = canary_count / n
        assert 0.05 <= ratio <= 0.15, f"Expected ~0.10, got {ratio:.4f}"


# ── Group 2: model_version label on EEP_REQUESTS ──────────────────────────────

class TestEEPRequestsLabel:
    """EEP_REQUESTS Counter is incremented with the correct model_version label."""

    def test_counter_has_model_version_label(self):
        from app.core.canary import EEP_REQUESTS
        # Verify the metric object has the expected label names.
        assert "model_version" in EEP_REQUESTS._labelnames

    def test_counter_increments_production_label(self):
        from app.core.canary import EEP_REQUESTS
        child = EEP_REQUESTS.labels(route="/test-prod", model_version="production")
        before = child._val
        child.inc()
        assert child._val == before + 1

    def test_counter_increments_canary_label(self):
        from app.core.canary import EEP_REQUESTS
        child = EEP_REQUESTS.labels(route="/test-canary", model_version="canary")
        before = child._val
        child.inc()
        assert child._val == before + 1


# ── Group 3: Canary eval pass/fail ────────────────────────────────────────────

class TestCanaryEvalEvaluate:
    """evaluate() returns correct pass/fail from metric values."""

    def _good_metrics(self):
        return {
            "prod_error_rate":        0.01,
            "canary_error_rate":      0.02,
            "prod_latency_p95":       0.20,
            "canary_latency_p95":     0.25,
            "prod_confidence_mean":   0.75,
            "canary_confidence_mean": 0.72,
        }

    def test_all_pass(self):
        from canary_eval import evaluate
        passed, failures = evaluate(self._good_metrics())
        assert passed is True
        assert failures == []

    def test_fail_error_rate(self):
        from canary_eval import evaluate
        m = self._good_metrics()
        m["canary_error_rate"] = 0.10  # > default 0.05
        passed, failures = evaluate(m)
        assert passed is False
        assert any("error rate" in f for f in failures)

    def test_fail_latency_p95(self):
        from canary_eval import evaluate
        m = self._good_metrics()
        m["canary_latency_p95"] = 0.8  # > default 0.5
        passed, failures = evaluate(m)
        assert passed is False
        assert any("latency p95" in f for f in failures)

    def test_fail_confidence(self):
        from canary_eval import evaluate
        m = self._good_metrics()
        m["canary_confidence_mean"] = 0.30  # < default 0.40
        passed, failures = evaluate(m)
        assert passed is False
        assert any("confidence mean" in f for f in failures)

    def test_multiple_failures_reported(self):
        from canary_eval import evaluate
        m = self._good_metrics()
        m["canary_error_rate"]      = 0.99
        m["canary_latency_p95"]     = 9.99
        m["canary_confidence_mean"] = 0.01
        passed, failures = evaluate(m)
        assert passed is False
        assert len(failures) == 3

    def test_none_metrics_are_skipped(self):
        """None values (Prometheus query returned no data) must not fail the check."""
        from canary_eval import evaluate
        m = {
            "prod_error_rate":        None,
            "canary_error_rate":      None,
            "prod_latency_p95":       None,
            "canary_latency_p95":     None,
            "prod_confidence_mean":   None,
            "canary_confidence_mean": None,
        }
        passed, failures = evaluate(m)
        assert passed is True
        assert failures == []

    def test_custom_thresholds_respected(self):
        from canary_eval import evaluate
        m = self._good_metrics()
        m["canary_error_rate"] = 0.03  # would pass default 0.05, fails custom 0.02
        passed, failures = evaluate(m, max_error_rate=0.02)
        assert passed is False
        assert any("error rate" in f for f in failures)

    def test_main_returns_0_on_pass(self):
        """main() exits 0 when Prometheus returns all-good metrics."""
        import canary_eval

        good_metrics = {
            "prod_error_rate":        0.01,
            "canary_error_rate":      0.02,
            "prod_latency_p95":       0.20,
            "canary_latency_p95":     0.25,
            "prod_confidence_mean":   0.75,
            "canary_confidence_mean": 0.72,
        }
        with (
            patch.object(canary_eval, "fetch_metrics", return_value=good_metrics),
            patch.object(canary_eval, "_log_to_mlflow"),
            patch.object(canary_eval, "rollback") as mock_rollback,
        ):
            rc = canary_eval.main()
        assert rc == 0
        mock_rollback.assert_not_called()

    def test_main_returns_1_on_fail(self):
        """main() exits 1 and calls rollback() when a check fails."""
        import canary_eval

        bad_metrics = {
            "prod_error_rate":        0.01,
            "canary_error_rate":      0.50,  # over threshold
            "prod_latency_p95":       0.20,
            "canary_latency_p95":     0.25,
            "prod_confidence_mean":   0.75,
            "canary_confidence_mean": 0.72,
        }
        with (
            patch.object(canary_eval, "fetch_metrics", return_value=bad_metrics),
            patch.object(canary_eval, "_log_to_mlflow"),
            patch.object(canary_eval, "rollback") as mock_rollback,
        ):
            rc = canary_eval.main()
        assert rc == 1
        mock_rollback.assert_called_once()


# ── Group 4: Rollback trigger ─────────────────────────────────────────────────

class TestRollback:
    """rollback() writes .env.canary and transitions the MLflow model version.

    mlflow is imported lazily inside rollback() with `import mlflow`, so we
    cannot use patch.object(canary_eval, "mlflow"). Instead we replace the
    entry in sys.modules so the `import mlflow` inside the function picks up
    our mock, then restore the original after each test.
    """

    def _mlflow_mock(self):
        mock_mlflow = MagicMock()
        mock_client = MagicMock()
        mock_mlflow.tracking.MlflowClient.return_value = mock_client
        return mock_mlflow, mock_client

    def test_writes_env_canary_file(self):
        import canary_eval
        mock_mlflow, _ = self._mlflow_mock()

        with tempfile.TemporaryDirectory() as tmpdir:
            env_file = os.path.join(tmpdir, ".env.canary")
            orig_env = canary_eval.ENV_CANARY_FILE
            canary_eval.ENV_CANARY_FILE = env_file

            orig_mlflow = sys.modules.get("mlflow")
            orig_tracking = sys.modules.get("mlflow.tracking")
            sys.modules["mlflow"] = mock_mlflow
            sys.modules["mlflow.tracking"] = mock_mlflow.tracking
            try:
                canary_eval.rollback(model_name="retailvision", version="2")
            finally:
                canary_eval.ENV_CANARY_FILE = orig_env
                sys.modules["mlflow"] = orig_mlflow
                if orig_tracking is not None:
                    sys.modules["mlflow.tracking"] = orig_tracking

            assert os.path.exists(env_file)
            content = open(env_file).read()
            assert "CANARY_PERCENTAGE=0" in content

    def test_transitions_mlflow_model_to_staging(self):
        import canary_eval
        mock_mlflow, mock_client = self._mlflow_mock()

        with tempfile.TemporaryDirectory() as tmpdir:
            env_file = os.path.join(tmpdir, ".env.canary")
            orig_env = canary_eval.ENV_CANARY_FILE
            canary_eval.ENV_CANARY_FILE = env_file

            orig_mlflow = sys.modules.get("mlflow")
            orig_tracking = sys.modules.get("mlflow.tracking")
            sys.modules["mlflow"] = mock_mlflow
            sys.modules["mlflow.tracking"] = mock_mlflow.tracking
            try:
                canary_eval.rollback(model_name="retailvision", version="2")
            finally:
                canary_eval.ENV_CANARY_FILE = orig_env
                sys.modules["mlflow"] = orig_mlflow
                if orig_tracking is not None:
                    sys.modules["mlflow.tracking"] = orig_tracking

            mock_client.transition_model_version_stage.assert_called_once_with(
                name="retailvision",
                version="2",
                stage="Staging",
                archive_existing_versions=False,
            )

    def test_env_file_write_failure_does_not_raise(self):
        """rollback() must not propagate OSError — non-fatal side effect."""
        import canary_eval
        mock_mlflow, _ = self._mlflow_mock()

        orig_env = canary_eval.ENV_CANARY_FILE
        canary_eval.ENV_CANARY_FILE = "/nonexistent/path/.env.canary"

        orig_mlflow = sys.modules.get("mlflow")
        orig_tracking = sys.modules.get("mlflow.tracking")
        sys.modules["mlflow"] = mock_mlflow
        sys.modules["mlflow.tracking"] = mock_mlflow.tracking
        try:
            canary_eval.rollback(model_name="retailvision", version="2")  # must not raise
        finally:
            canary_eval.ENV_CANARY_FILE = orig_env
            sys.modules["mlflow"] = orig_mlflow
            if orig_tracking is not None:
                sys.modules["mlflow.tracking"] = orig_tracking

    def test_mlflow_failure_does_not_raise(self):
        """rollback() must not propagate MLflow errors — non-fatal side effect."""
        import canary_eval

        mock_mlflow = MagicMock()
        mock_mlflow.tracking.MlflowClient.side_effect = RuntimeError("MLflow down")

        with tempfile.TemporaryDirectory() as tmpdir:
            env_file = os.path.join(tmpdir, ".env.canary")
            orig_env = canary_eval.ENV_CANARY_FILE
            canary_eval.ENV_CANARY_FILE = env_file

            orig_mlflow = sys.modules.get("mlflow")
            orig_tracking = sys.modules.get("mlflow.tracking")
            sys.modules["mlflow"] = mock_mlflow
            sys.modules["mlflow.tracking"] = mock_mlflow.tracking
            try:
                canary_eval.rollback(model_name="retailvision", version="2")  # must not raise
            finally:
                canary_eval.ENV_CANARY_FILE = orig_env
                sys.modules["mlflow"] = orig_mlflow
                if orig_tracking is not None:
                    sys.modules["mlflow.tracking"] = orig_tracking
