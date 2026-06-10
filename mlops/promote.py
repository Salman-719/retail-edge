"""MLflow registry transition functions for the promotion ladder.

State model
-----------
MLflow has four built-in registry stages: None, Staging, Production, Archived.
Shadow and canary are not built-in stages, so we represent them as the tag
``promotion_state`` on a model version (value: "shadow" or "canary") while
keeping the version in stage ``None``.  This keeps the registry vocabulary
clean while making the live state machine-queryable via the tag API.

Stage/tag map:

  MLflow stage  │  promotion_state tag  │  Meaning
  ──────────────┼───────────────────────┼──────────────────────────────────
  Staging       │  (absent)             │  Candidate waiting to enter ladder
  None          │  shadow               │  Under shadow evaluation
  None          │  canary               │  Under canary traffic split
  Production    │  (absent)             │  Live production model
  Archived      │  rejected / superseded│  No longer active; reason recorded

Every transition:
  1. Updates the version stage and/or ``promotion_state`` tag.
  2. Sets a human-readable ``description`` on the version.
  3. Logs a run to the ``promotion_ladder`` MLflow experiment with full
     audit context: model_name, version, from_stage/tag, to_stage/tag,
     reason, triggered_by, timestamp.

No subprocess or deployment logic lives here — that is run_promotion.py's job.
"""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone

log = logging.getLogger("promote")

MLFLOW_TRACKING_URI = os.environ.get("MLFLOW_TRACKING_URI", "http://localhost:5000")
PROMOTION_EXPERIMENT = "promotion_ladder"


# ── Internal helpers ───────────────────────────────────────────────────────────

def _client():
    import mlflow
    from mlflow.tracking import MlflowClient
    mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)
    return MlflowClient()


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _current_state(client, model_name: str, version: str) -> tuple[str, str]:
    """Return (mlflow_stage, promotion_state_tag) for a version."""
    mv = client.get_model_version(model_name, version)
    stage = mv.current_stage
    tag = ""
    for t in (mv.tags or {}):
        if t == "promotion_state":
            tag = mv.tags[t]
            break
    return stage, tag


def _log_transition(
    *,
    model_name: str,
    version: str,
    from_stage: str,
    from_tag: str,
    to_stage: str,
    to_tag: str,
    reason: str,
    triggered_by: str,
    extra_metrics: dict | None = None,
) -> None:
    """Log one MLflow run recording a registry transition."""
    try:
        import mlflow
        mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)
        mlflow.set_experiment(PROMOTION_EXPERIMENT)
        with mlflow.start_run(
            run_name=f"{model_name}_v{version}_{to_stage or to_tag}",
        ):
            mlflow.log_params({
                "model_name":   model_name,
                "model_version": version,
                "from_stage":   from_stage,
                "from_tag":     from_tag,
                "to_stage":     to_stage,
                "to_tag":       to_tag,
                "reason":       reason,
                "triggered_by": triggered_by,
                "timestamp":    _now_iso(),
            })
            if extra_metrics:
                mlflow.log_metrics(extra_metrics)
    except Exception as exc:
        log.warning("_log_transition: MLflow logging failed (non-fatal): %s", exc)


def _set_version_tag(client, model_name: str, version: str, key: str, value: str) -> None:
    try:
        client.set_model_version_tag(model_name, version, key, value)
    except Exception as exc:
        log.warning("set_model_version_tag failed: %s", exc)


def _delete_version_tag(client, model_name: str, version: str, key: str) -> None:
    try:
        client.delete_model_version_tag(model_name, version, key)
    except Exception as exc:
        log.warning("delete_model_version_tag failed: %s", exc)


# ── Public transition API ──────────────────────────────────────────────────────

def move_to_shadow(
    model_name: str,
    version: str,
    triggered_by: str = "run_promotion.py",
) -> None:
    """Staging → shadow evaluation.

    Sets promotion_state=shadow tag on the version (stage stays None since
    MLflow has no shadow stage). Versions must be in Staging before calling.
    """
    client = _client()
    from_stage, from_tag = _current_state(client, model_name, version)

    client.transition_model_version_stage(
        name=model_name,
        version=version,
        stage="None",
        archive_existing_versions=False,
    )
    _set_version_tag(client, model_name, version, "promotion_state", "shadow")
    client.update_model_version(
        name=model_name,
        version=version,
        description=f"[shadow] Entered shadow evaluation at {_now_iso()}.",
    )

    log.info("promote: %s v%s  %s/%s → None/shadow", model_name, version, from_stage, from_tag)
    _log_transition(
        model_name=model_name,
        version=version,
        from_stage=from_stage,
        from_tag=from_tag,
        to_stage="None",
        to_tag="shadow",
        reason="entered shadow evaluation window",
        triggered_by=triggered_by,
    )


def move_to_canary(
    model_name: str,
    version: str,
    canary_percentage: int,
    triggered_by: str = "run_promotion.py",
) -> None:
    """Shadow → canary traffic split.

    Updates promotion_state tag from shadow → canary. Records the configured
    canary_percentage as a param so the audit trail shows what split was used.
    """
    client = _client()
    from_stage, from_tag = _current_state(client, model_name, version)

    _set_version_tag(client, model_name, version, "promotion_state", "canary")
    _set_version_tag(client, model_name, version, "canary_percentage", str(canary_percentage))
    client.update_model_version(
        name=model_name,
        version=version,
        description=(
            f"[canary] Entered canary split ({canary_percentage}%) at {_now_iso()}. "
            "Shadow evaluation passed."
        ),
    )

    log.info(
        "promote: %s v%s  %s/%s → None/canary (%d%%)",
        model_name, version, from_stage, from_tag, canary_percentage,
    )
    _log_transition(
        model_name=model_name,
        version=version,
        from_stage=from_stage,
        from_tag=from_tag,
        to_stage="None",
        to_tag="canary",
        reason=f"shadow evaluation passed; starting canary at {canary_percentage}%",
        triggered_by=triggered_by,
        extra_metrics={"canary_percentage": float(canary_percentage)},
    )


def move_to_production(
    model_name: str,
    version: str,
    triggered_by: str = "run_promotion.py",
) -> None:
    """Canary → Production (full traffic).

    Promotes the version to Production in the MLflow registry.
    ``archive_existing_versions=True`` automatically moves any previously
    Production version to Archived and tags it "superseded".
    """
    client = _client()
    from_stage, from_tag = _current_state(client, model_name, version)

    # Find the current Production version(s) so we can tag them as superseded.
    try:
        prod_versions = client.get_latest_versions(model_name, stages=["Production"])
    except Exception:
        prod_versions = []

    client.transition_model_version_stage(
        name=model_name,
        version=version,
        stage="Production",
        archive_existing_versions=True,
    )
    _delete_version_tag(client, model_name, version, "promotion_state")
    client.update_model_version(
        name=model_name,
        version=version,
        description=f"[production] Promoted to full production at {_now_iso()}. Canary evaluation passed.",
    )

    # Tag superseded versions for traceability.
    for pv in prod_versions:
        if pv.version != version:
            _set_version_tag(client, model_name, pv.version, "promotion_state", "superseded")
            client.update_model_version(
                name=model_name,
                version=pv.version,
                description=f"[archived] Superseded by v{version} at {_now_iso()}.",
            )

    log.info("promote: %s v%s  %s/%s → Production", model_name, version, from_stage, from_tag)
    _log_transition(
        model_name=model_name,
        version=version,
        from_stage=from_stage,
        from_tag=from_tag,
        to_stage="Production",
        to_tag="",
        reason="canary evaluation passed; full promotion",
        triggered_by=triggered_by,
    )


def rollback(
    model_name: str,
    version: str,
    reason: str,
    triggered_by: str = "run_promotion.py",
    eval_exit_code: int | None = None,
) -> None:
    """Any active state → Archived.

    Archives the version, records the rejection reason on the version
    description (visible in MLflow UI), and logs a promotion_ladder run so
    the failure is auditable without opening the run detail view.
    """
    client = _client()
    from_stage, from_tag = _current_state(client, model_name, version)

    client.transition_model_version_stage(
        name=model_name,
        version=version,
        stage="Archived",
        archive_existing_versions=False,
    )
    _set_version_tag(client, model_name, version, "promotion_state", "rejected")
    _set_version_tag(client, model_name, version, "rejection_reason", reason[:500])
    client.update_model_version(
        name=model_name,
        version=version,
        description=(
            f"[archived/rejected] {_now_iso()} — {reason}. "
            f"Was in stage={from_stage}/tag={from_tag} when rejected."
        ),
    )

    log.warning(
        "promote: ROLLBACK %s v%s  %s/%s → Archived  reason=%r",
        model_name, version, from_stage, from_tag, reason,
    )
    extra: dict = {}
    if eval_exit_code is not None:
        extra["eval_exit_code"] = float(eval_exit_code)
    _log_transition(
        model_name=model_name,
        version=version,
        from_stage=from_stage,
        from_tag=from_tag,
        to_stage="Archived",
        to_tag="rejected",
        reason=reason,
        triggered_by=triggered_by,
        extra_metrics=extra or None,
    )
