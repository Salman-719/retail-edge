"""Full promotion ladder orchestrator.

Discovers the oldest Staging model version and drives it through:
  Staging → shadow → canary → Production

Each step invokes compare_shadow.py or canary_eval.py as a subprocess and
checks the exit code.  On any failure the version is archived via rollback()
and the script exits 1.

Usage
-----
    python mlops/run_promotion.py [--model-name NAME] [--dry-run]

Environment variables
---------------------
    MLFLOW_TRACKING_URI          Default: http://localhost:5000
    PROMOTION_MODEL_NAME         Registered model name. Default: retailvision
    SHADOW_WINDOW_SECONDS        How long to run shadow before comparing. Default: 300
    CANARY_WINDOW_SECONDS        How long to run canary before evaluating. Default: 1800
    CANARY_PERCENTAGE            Traffic split % for the canary window. Default: 10
    COMPARE_SHADOW_SCRIPT        Path to compare_shadow.py. Default: mlops/compare_shadow.py
    CANARY_EVAL_SCRIPT           Path to canary_eval.py. Default: mlops/canary_eval.py
    PROMOTION_DRY_RUN            Set to "1" to skip subprocess calls (plan only).
"""
from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys
import time

log = logging.getLogger("run_promotion")

# ── Configuration ──────────────────────────────────────────────────────────────

MLFLOW_TRACKING_URI   = os.environ.get("MLFLOW_TRACKING_URI",    "http://localhost:5000")
PROMOTION_MODEL_NAME  = os.environ.get("PROMOTION_MODEL_NAME",   "retailvision")
SHADOW_WINDOW_SECONDS = int(os.environ.get("SHADOW_WINDOW_SECONDS",  "300"))
CANARY_WINDOW_SECONDS = int(os.environ.get("CANARY_WINDOW_SECONDS",  "1800"))
CANARY_PERCENTAGE     = int(os.environ.get("CANARY_PERCENTAGE",       "10"))

_SCRIPT_DIR = os.path.dirname(__file__)
COMPARE_SHADOW_SCRIPT = os.environ.get(
    "COMPARE_SHADOW_SCRIPT",
    os.path.join(_SCRIPT_DIR, "compare_shadow.py"),
)
CANARY_EVAL_SCRIPT = os.environ.get(
    "CANARY_EVAL_SCRIPT",
    os.path.join(_SCRIPT_DIR, "canary_eval.py"),
)
DRY_RUN = os.environ.get("PROMOTION_DRY_RUN", "0") == "1"


# ── MLflow helpers ─────────────────────────────────────────────────────────────

def _mlflow_client():
    import mlflow
    from mlflow.tracking import MlflowClient
    mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)
    return MlflowClient()


def _log_step(experiment: str, run_name: str, params: dict, metrics: dict | None = None) -> None:
    """Log a single promotion step to MLflow (non-fatal on failure)."""
    try:
        import mlflow
        mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)
        mlflow.set_experiment(experiment)
        with mlflow.start_run(run_name=run_name):
            mlflow.log_params(params)
            if metrics:
                mlflow.log_metrics(metrics)
    except Exception as exc:
        log.warning("_log_step: MLflow logging failed (non-fatal): %s", exc)


def _find_staging_version(client, model_name: str) -> str | None:
    """Return the version string of the oldest Staging version, or None."""
    try:
        versions = client.get_latest_versions(model_name, stages=["Staging"])
    except Exception as exc:
        log.error("Cannot query MLflow registry: %s", exc)
        return None
    if not versions:
        return None
    # Oldest first — promotes in the order candidates were registered.
    versions.sort(key=lambda v: int(v.version))
    return versions[0].version


# ── Step runners ──────────────────────────────────────────────────────────────

def _run_subprocess(script: str, extra_env: dict | None = None) -> int:
    """Run a Python script as a subprocess; return its exit code."""
    if DRY_RUN:
        log.info("DRY RUN: would run %s", script)
        return 0
    env = {**os.environ, **(extra_env or {})}
    result = subprocess.run(
        [sys.executable, script],
        env=env,
    )
    return result.returncode


def _step_shadow(model_name: str, version: str) -> bool:
    """Deploy to shadow, wait the shadow window, run compare_shadow.py.

    Returns True on pass, False on fail.
    """
    import promote

    promote.move_to_shadow(model_name, version, triggered_by="run_promotion.py:step_shadow")

    log.info("Shadow window: sleeping %ds before comparison…", SHADOW_WINDOW_SECONDS)
    if not DRY_RUN:
        time.sleep(SHADOW_WINDOW_SECONDS)

    log.info("Running compare_shadow.py…")
    rc = _run_subprocess(COMPARE_SHADOW_SCRIPT)

    _log_step(
        experiment="promotion_ladder",
        run_name=f"{model_name}_v{version}_shadow_eval",
        params={
            "model_name":    model_name,
            "model_version": version,
            "step":          "shadow",
            "window_seconds": str(SHADOW_WINDOW_SECONDS),
            "script":        COMPARE_SHADOW_SCRIPT,
        },
        metrics={"shadow_eval_exit_code": float(rc)},
    )

    if rc != 0:
        log.warning("Shadow evaluation FAILED (exit %d)", rc)
        promote.rollback(
            model_name, version,
            reason=f"compare_shadow.py exited {rc} — shadow metrics outside thresholds",
            triggered_by="run_promotion.py:step_shadow",
            eval_exit_code=rc,
        )
        return False

    log.info("Shadow evaluation PASSED.")
    return True


def _step_canary(model_name: str, version: str) -> bool:
    """Deploy to canary, wait canary window, run canary_eval.py.

    Returns True on pass, False on fail.
    """
    import promote

    promote.move_to_canary(
        model_name, version,
        canary_percentage=CANARY_PERCENTAGE,
        triggered_by="run_promotion.py:step_canary",
    )

    log.info(
        "Canary window (%d%%): sleeping %ds before evaluation…",
        CANARY_PERCENTAGE, CANARY_WINDOW_SECONDS,
    )
    if not DRY_RUN:
        time.sleep(CANARY_WINDOW_SECONDS)

    log.info("Running canary_eval.py…")
    rc = _run_subprocess(
        CANARY_EVAL_SCRIPT,
        extra_env={"CANARY_VERSION": version, "CANARY_PERCENTAGE": str(CANARY_PERCENTAGE)},
    )

    _log_step(
        experiment="promotion_ladder",
        run_name=f"{model_name}_v{version}_canary_eval",
        params={
            "model_name":       model_name,
            "model_version":    version,
            "step":             "canary",
            "window_seconds":   str(CANARY_WINDOW_SECONDS),
            "canary_percentage": str(CANARY_PERCENTAGE),
            "script":           CANARY_EVAL_SCRIPT,
        },
        metrics={"canary_eval_exit_code": float(rc)},
    )

    if rc != 0:
        log.warning("Canary evaluation FAILED (exit %d)", rc)
        promote.rollback(
            model_name, version,
            reason=f"canary_eval.py exited {rc} — canary metrics outside thresholds",
            triggered_by="run_promotion.py:step_canary",
            eval_exit_code=rc,
        )
        return False

    log.info("Canary evaluation PASSED.")
    return True


def _step_promote(model_name: str, version: str) -> None:
    """Promote to full production and log the result."""
    import promote

    promote.move_to_production(model_name, version, triggered_by="run_promotion.py:step_promote")

    _log_step(
        experiment="promotion_ladder",
        run_name=f"{model_name}_v{version}_promoted",
        params={
            "model_name":    model_name,
            "model_version": version,
            "step":          "production",
        },
        metrics={"promoted": 1.0},
    )
    log.info("Model %s v%s is now Production.", model_name, version)


# ── Entry point ────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    parser = argparse.ArgumentParser(description="RetailVision promotion ladder")
    parser.add_argument("--model-name", default=PROMOTION_MODEL_NAME)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    model_name = args.model_name
    global DRY_RUN  # noqa: PLW0603
    if args.dry_run:
        DRY_RUN = True

    if DRY_RUN:
        log.info("DRY RUN mode — no subprocesses or registry writes will occur.")

    # ── Step 1: find a Staging candidate ──────────────────────────────────────
    client = _mlflow_client()
    version = _find_staging_version(client, model_name)

    if version is None:
        log.info("No Staging version found for %r — nothing to promote. Exiting 0.", model_name)
        return 0

    log.info("Found candidate: %s v%s in Staging.", model_name, version)

    # ── Step 2: shadow ────────────────────────────────────────────────────────
    log.info("── Step 2: shadow evaluation ──────────────────────")
    if not _step_shadow(model_name, version):
        log.error("Promotion halted at shadow step.")
        return 1

    # ── Step 3: canary ────────────────────────────────────────────────────────
    log.info("── Step 3: canary evaluation ──────────────────────")
    if not _step_canary(model_name, version):
        log.error("Promotion halted at canary step.")
        return 1

    # ── Step 4: full production ───────────────────────────────────────────────
    log.info("── Step 4: promote to production ──────────────────")
    _step_promote(model_name, version)

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
