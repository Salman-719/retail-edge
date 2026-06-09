"""Canary evaluation job.

Queries Prometheus for canary request flow plus platform/model metrics,
checks three conditions,
logs results to MLflow experiment "canary_eval", and exits 0 (pass) or 1 (fail).

On failure it also transitions the canary model registration in MLflow back to
Staging. Kubernetes traffic changes remain an explicit operator action via Helm:
set eep.canaryPercentage back to 0 and redeploy.

Usage
-----
    python mlops/canary_eval.py

Environment variables
---------------------
    PROMETHEUS_URL            Prometheus base URL. Default: http://localhost:9090
    MLFLOW_TRACKING_URI       Default: http://localhost:5000
    CANARY_MODEL_NAME         MLflow registered model name. Default: retailvision
    CANARY_VERSION            MLflow model version to demote on rollback. Default: 2

Threshold env vars (all optional — defaults shown)
---------------------------------------------------
    CANARY_MAX_ERROR_RATE     Maximum allowed aggregate EEP HTTP 5xx rate. Default: 0.05
    CANARY_MAX_LATENCY_P95    Maximum aggregate EEP p95 latency in seconds. Default: 0.5
    CANARY_MIN_CONFIDENCE     Minimum canary detection_confidence mean. Default: 0.40
    CANARY_LOOKBACK_MINUTES   Prometheus lookback window in minutes. Default: 30
    CANARY_REQUIRE_TRAFFIC    Fail if no canary-tagged EEP requests. Default: 1
"""
from __future__ import annotations

import logging
import os
import sys
import time

import requests

log = logging.getLogger("canary_eval")

# ── Configuration ──────────────────────────────────────────────────────────────

PROMETHEUS_URL       = os.environ.get("PROMETHEUS_URL",       "http://localhost:9090")
MLFLOW_TRACKING_URI  = os.environ.get("MLFLOW_TRACKING_URI",  "http://localhost:5000")
CANARY_MODEL_NAME    = os.environ.get("CANARY_MODEL_NAME",    "retailvision")
CANARY_VERSION       = os.environ.get("CANARY_VERSION",       "2")

CANARY_MAX_ERROR_RATE    = float(os.environ.get("CANARY_MAX_ERROR_RATE",    "0.05"))
CANARY_MAX_LATENCY_P95   = float(os.environ.get("CANARY_MAX_LATENCY_P95",   "0.5"))
CANARY_MIN_CONFIDENCE    = float(os.environ.get("CANARY_MIN_CONFIDENCE",    "0.40"))
CANARY_LOOKBACK_MINUTES  = int(os.environ.get("CANARY_LOOKBACK_MINUTES",    "30"))
CANARY_REQUIRE_TRAFFIC   = os.environ.get("CANARY_REQUIRE_TRAFFIC", "1") != "0"

ENV_CANARY_FILE = os.environ.get("CANARY_ENV_FILE", ".env.canary")


# ── Prometheus query helpers ───────────────────────────────────────────────────

def _instant_query(expr: str, prometheus_url: str = PROMETHEUS_URL) -> float | None:
    """Execute a Prometheus instant query; return scalar value or None."""
    try:
        resp = requests.get(
            f"{prometheus_url}/api/v1/query",
            params={"query": expr},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        result = data.get("data", {}).get("result", [])
        if not result:
            return None
        return float(result[0]["value"][1])
    except Exception as exc:
        log.warning("Prometheus query failed: %s — %s", expr, exc)
        return None


def fetch_metrics(
    lookback_minutes: int = CANARY_LOOKBACK_MINUTES,
    prometheus_url: str = PROMETHEUS_URL,
) -> dict[str, float | None]:
    """Return a dict of raw metric values for production and canary."""
    window = f"{lookback_minutes}m"

    def q(expr: str) -> float | None:
        return _instant_query(expr, prometheus_url)

    # EEP canary middleware emits request counts by model_version. The default
    # FastAPI instrumentator emits aggregate latency/errors, not model_version
    # split latency/errors, so canary_eval gates platform health aggregate and
    # model confidence by detector model_version when canary detector metrics exist.
    eep_errors = q(
        f'sum(rate(http_requests_total{{status=~"5..",job="eep"}}[{window}])) or vector(0)'
    )
    eep_total = q(
        f'sum(rate(http_requests_total{{job="eep"}}[{window}])) or vector(0)'
    )
    prod_request_rate = q(
        f'sum(rate(eep_requests_total{{model_version="production"}}[{window}])) or vector(0)'
    )
    canary_request_rate = q(
        f'sum(rate(eep_requests_total{{model_version="canary"}}[{window}])) or vector(0)'
    )

    eep_latency_p95 = q(
        f'histogram_quantile(0.95, sum by (le) (rate(http_request_duration_seconds_bucket{{job="eep"}}[{window}])))'
    )

    # Detection confidence mean: use the YOLO service metric (model_version label).
    prod_confidence = q(
        f'avg(rate(detector_detection_confidence_sum{{model_version="production"}}[{window}])) / avg(rate(detector_detection_confidence_count{{model_version="production"}}[{window}]))'
    )
    canary_confidence = q(
        f'avg(rate(detector_detection_confidence_sum{{model_version="canary"}}[{window}])) / avg(rate(detector_detection_confidence_count{{model_version="canary"}}[{window}]))'
    )

    return {
        "eep_error_rate":       (eep_errors / eep_total) if (eep_errors is not None and eep_total and eep_total > 0) else 0.0,
        "eep_latency_p95":      eep_latency_p95,
        "prod_request_rate":    prod_request_rate,
        "canary_request_rate":  canary_request_rate,
        "prod_confidence_mean": prod_confidence,
        "canary_confidence_mean": canary_confidence,
    }


# ── Pass/fail evaluation ───────────────────────────────────────────────────────

def evaluate(
    metrics: dict[str, float | None],
    max_error_rate: float = CANARY_MAX_ERROR_RATE,
    max_latency_p95: float = CANARY_MAX_LATENCY_P95,
    min_confidence: float = CANARY_MIN_CONFIDENCE,
) -> tuple[bool, list[str]]:
    """Apply pass/fail thresholds to the fetched metrics.

    Returns (passed: bool, failures: list[str]).
    An empty failures list means all checks passed.
    """
    failures: list[str] = []

    if CANARY_REQUIRE_TRAFFIC and (metrics.get("canary_request_rate") or 0.0) <= 0.0:
        failures.append("no canary-tagged EEP requests observed")

    canary_error = metrics.get("eep_error_rate")
    if canary_error is not None and canary_error > max_error_rate:
        failures.append(
            f"EEP aggregate error rate {canary_error:.4f} > threshold {max_error_rate:.4f}"
        )

    canary_p95 = metrics.get("eep_latency_p95")
    if canary_p95 is not None and canary_p95 > max_latency_p95:
        failures.append(
            f"EEP aggregate latency p95 {canary_p95:.3f}s > threshold {max_latency_p95:.3f}s"
        )

    canary_conf = metrics.get("canary_confidence_mean")
    if canary_conf is not None and canary_conf < min_confidence:
        failures.append(
            f"canary confidence mean {canary_conf:.4f} < threshold {min_confidence:.4f}"
        )

    return (len(failures) == 0), failures


# ── Rollback ───────────────────────────────────────────────────────────────────

def rollback(model_name: str = CANARY_MODEL_NAME, version: str = CANARY_VERSION) -> None:
    """Write an operator hint and demote the model version in MLflow."""
    try:
        with open(ENV_CANARY_FILE, "w") as f:
            f.write("HELM_SET_EEP_CANARY_PERCENTAGE=0\n")
        log.warning("Rollback hint: wrote Helm canary reset to %s", ENV_CANARY_FILE)
    except OSError as exc:
        log.error("Rollback: could not write %s: %s", ENV_CANARY_FILE, exc)

    try:
        import mlflow
        from mlflow.tracking import MlflowClient

        mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)
        client = MlflowClient()
        client.transition_model_version_stage(
            name=model_name,
            version=version,
            stage="Staging",
            archive_existing_versions=False,
        )
        log.warning(
            "Rollback: transitioned %s v%s → Staging in MLflow registry",
            model_name,
            version,
        )
    except Exception as exc:
        log.error("Rollback: MLflow registry transition failed: %s", exc)


# ── MLflow logging ─────────────────────────────────────────────────────────────

def _log_to_mlflow(
    metrics: dict[str, float | None],
    passed: bool,
    failures: list[str],
    thresholds: dict[str, float],
) -> None:
    try:
        import mlflow

        mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)
        mlflow.set_experiment("canary_eval")
        with mlflow.start_run():
            mlflow.log_params(thresholds)
            for k, v in metrics.items():
                if v is not None:
                    mlflow.log_metric(k, v)
            mlflow.log_metric("eval_passed", float(passed))
            mlflow.log_param("failure_reasons", "; ".join(failures) if failures else "none")
            mlflow.log_param("evaluated_at", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    except Exception as exc:
        log.warning("MLflow logging failed (non-fatal): %s", exc)


# ── Entry point ────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    thresholds = {
        "max_error_rate":   CANARY_MAX_ERROR_RATE,
        "max_latency_p95":  CANARY_MAX_LATENCY_P95,
        "min_confidence":   CANARY_MIN_CONFIDENCE,
        "lookback_minutes": CANARY_LOOKBACK_MINUTES,
    }

    log.info(
        "Canary eval starting  prometheus=%s  window=%dm",
        PROMETHEUS_URL,
        CANARY_LOOKBACK_MINUTES,
    )

    metrics = fetch_metrics()
    log.info("Fetched metrics: %s", metrics)

    passed, failures = evaluate(metrics)

    _log_to_mlflow(metrics, passed, failures, thresholds)

    if passed:
        log.info("Canary eval PASSED — all checks within thresholds")
        return 0

    log.warning("Canary eval FAILED — %d check(s) failed:", len(failures))
    for reason in failures:
        log.warning("  ✗ %s", reason)

    rollback()
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
