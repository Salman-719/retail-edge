"""Shared MLflow logging helper for the offline eval scripts.

Every run logged through `log_run()` automatically carries reproducibility
context (Gap 5): the random seed, the git commit, and the pinned requirements.txt.
Callers must pass `phase`, `scene`, and `metric_type` tags.

Storage: params/metrics → Postgres `mlflow` DB; artifacts → MinIO `mlflow` bucket.
The eval client only ever talks to the tracking server at MLFLOW_TRACKING_URI.
"""
from __future__ import annotations

import os
import subprocess
from contextlib import contextmanager

import mlflow

TRACKING_URI = os.environ.get("MLFLOW_TRACKING_URI", "http://localhost:5000")

# Harmless to set even when the server uses --serve-artifacts (it proxies artifacts).
os.environ.setdefault("MLFLOW_S3_ENDPOINT_URL", "http://localhost:9000")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "retailvision")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "retailvision_dev")

mlflow.set_tracking_uri(TRACKING_URI)

# System-metrics sampler interval (seconds). MLflow's default is 10s, so very
# short runs (e.g. the yolov8n smoke run, ~1s) finish before the first sample and
# show "No system metrics recorded". 2s captures the longer real runs (rtdetr-x
# takes minutes). Sub-2s smoke runs may still show none — expected, not a bug.
os.environ.setdefault("MLFLOW_SYSTEM_METRICS_SAMPLING_INTERVAL", "2")

_REQUIREMENTS = os.path.join(os.path.dirname(__file__), "requirements.txt")


def _git_commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"]).decode().strip()
    except Exception:
        return "unknown"


@contextmanager
def run_context(experiment: str, run_name: str):
    """Open an MLflow run AROUND the heavy work (inference), then log inside it.

    Why a context manager and not just log_run(): the system-metrics monitor only
    samples while the run is open. If you do all the inference first and call
    log_run() at the end, the run lives ~1 s and records ZERO system metrics. Doing
    the inference INSIDE this `with` block keeps the monitor alive for the whole
    job, so CPU/RAM are actually captured.

    Usage:
        with run_context("detection", name):
            stats = run_detection_clip(...)        # monitored
            log_metrics_params_artifacts(params, metrics, tags, artifacts)
    """
    mlflow.set_experiment(experiment)
    with mlflow.start_run(run_name=run_name, log_system_metrics=True) as run:
        yield run


def log_metrics_params_artifacts(params, metrics, tags=None, artifacts=None, seed=42) -> None:
    """Log params/metrics/tags/artifacts into the CURRENTLY-OPEN run. Always adds
    the Gap-5 reproducibility context (seed, git_commit, requirements.txt)."""
    mlflow.log_params({**params, "seed": seed})
    mlflow.set_tags({**(tags or {}), "git_commit": _git_commit()})
    mlflow.log_metrics(metrics)
    if os.path.exists(_REQUIREMENTS):
        mlflow.log_artifact(_REQUIREMENTS)
    for path in artifacts or []:
        if path and os.path.exists(path):
            mlflow.log_artifact(path)


def log_run(
    experiment: str,
    run_name: str,
    params: dict,
    metrics: dict,
    tags: dict | None = None,
    artifacts: list[str] | None = None,
    seed: int = 42,
) -> str:
    """Convenience: open a run and log everything in one call. NOTE: this records
    no system metrics unless the heavy work happens inside the run — prefer
    run_context() + log_metrics_params_artifacts() for that. Kept for simple cases."""
    with run_context(experiment, run_name) as run:
        log_metrics_params_artifacts(params, metrics, tags, artifacts, seed)
        return run.info.run_id
