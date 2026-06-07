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

import mlflow

TRACKING_URI = os.environ.get("MLFLOW_TRACKING_URI", "http://localhost:5000")

# Harmless to set even when the server uses --serve-artifacts (it proxies artifacts).
os.environ.setdefault("MLFLOW_S3_ENDPOINT_URL", "http://localhost:9000")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "retailvision")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "retailvision_dev")

mlflow.set_tracking_uri(TRACKING_URI)

_REQUIREMENTS = os.path.join(os.path.dirname(__file__), "requirements.txt")


def _git_commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"]).decode().strip()
    except Exception:
        return "unknown"


def log_run(
    experiment: str,
    run_name: str,
    params: dict,
    metrics: dict,
    tags: dict | None = None,
    artifacts: list[str] | None = None,
    seed: int = 42,
) -> str:
    """Log one evaluation run. Returns the run_id.

    Gap 5 (reproducibility) is enforced here: seed param, git_commit tag, and
    requirements.txt artifact are always attached.
    Gap 6 (per-video runs): callers must pass tags['scene'].
    """
    mlflow.set_experiment(experiment)
    with mlflow.start_run(run_name=run_name) as run:
        mlflow.log_params({**params, "seed": seed})
        mlflow.set_tags({**(tags or {}), "git_commit": _git_commit()})
        mlflow.log_metrics(metrics)
        if os.path.exists(_REQUIREMENTS):
            mlflow.log_artifact(_REQUIREMENTS)
        for path in artifacts or []:
            if path and os.path.exists(path):
                mlflow.log_artifact(path)
        return run.info.run_id
