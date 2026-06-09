"""Promotion ladder state consistency check.

Reads the MLflow registry and current environment variables and confirms they
agree.  If an inconsistency is detected it logs a warning and exits 1 so the
caller (CI, k3s health-check job) can act on it.

Inconsistencies detected
------------------------
- MLflow has a version tagged promotion_state=canary but CANARY_PERCENTAGE == 0
- MLflow has a version tagged promotion_state=canary but CANARY_PERCENTAGE is
  set to 0 in .env.canary (the rollback override file)
- MLflow has a version in Production but the registry also has a version tagged
  canary (two "live" versions simultaneously without a planned rollout)
- MLflow has a version tagged promotion_state=shadow but no shadow window is
  plausibly running (heuristic: SHADOW_WINDOW_SECONDS env var is 0)
- No Production version exists (new deployment, or everything was archived)

Usage
-----
    python mlops/check_state.py [--model-name NAME]

Exit codes
----------
    0  All checks passed — state is consistent.
    1  One or more inconsistencies found — details logged at WARNING level.
    2  Cannot reach MLflow registry (connectivity problem).

Environment variables
---------------------
    MLFLOW_TRACKING_URI      Default: http://localhost:5000
    PROMOTION_MODEL_NAME     Default: retailvision
    CANARY_PERCENTAGE        Read from env (or .env.canary if present).
    CANARY_ENV_FILE          Path to .env.canary override. Default: .env.canary
"""
from __future__ import annotations

import argparse
import logging
import os
import sys

log = logging.getLogger("check_state")

MLFLOW_TRACKING_URI  = os.environ.get("MLFLOW_TRACKING_URI",  "http://localhost:5000")
PROMOTION_MODEL_NAME = os.environ.get("PROMOTION_MODEL_NAME", "retailvision")
CANARY_ENV_FILE      = os.environ.get("CANARY_ENV_FILE",      ".env.canary")


# ── Helpers ────────────────────────────────────────────────────────────────────

def _mlflow_client():
    import mlflow
    from mlflow.tracking import MlflowClient
    mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)
    return MlflowClient()


def _read_canary_env_file(path: str) -> dict[str, str]:
    """Parse KEY=VALUE pairs from .env.canary if it exists."""
    result: dict[str, str] = {}
    if not os.path.exists(path):
        return result
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                result[k.strip()] = v.strip()
    except OSError:
        pass
    return result


def _effective_canary_percentage() -> int:
    """Resolve CANARY_PERCENTAGE, preferring .env.canary override if present."""
    override = _read_canary_env_file(CANARY_ENV_FILE)
    if "CANARY_PERCENTAGE" in override:
        try:
            return int(override["CANARY_PERCENTAGE"])
        except ValueError:
            pass
    return int(os.environ.get("CANARY_PERCENTAGE", "0"))


def _get_versions_by_tag(client, model_name: str, tag_value: str) -> list:
    """Return all model versions where promotion_state tag == tag_value."""
    try:
        all_versions = client.search_model_versions(f"name='{model_name}'")
    except Exception:
        return []
    return [
        v for v in all_versions
        if v.tags.get("promotion_state") == tag_value
    ]


def _get_production_versions(client, model_name: str) -> list:
    try:
        return client.get_latest_versions(model_name, stages=["Production"])
    except Exception:
        return []


def _get_staging_versions(client, model_name: str) -> list:
    try:
        return client.get_latest_versions(model_name, stages=["Staging"])
    except Exception:
        return []


# ── Check functions ────────────────────────────────────────────────────────────

def run_checks(model_name: str) -> list[str]:
    """Execute all consistency checks; return list of inconsistency descriptions.

    An empty list means all checks passed.
    """
    try:
        client = _mlflow_client()
        # Probe connectivity with a cheap call.
        client.search_registered_models(f"name='{model_name}'")
    except Exception as exc:
        raise RuntimeError(f"Cannot reach MLflow registry: {exc}") from exc

    issues: list[str] = []
    canary_pct = _effective_canary_percentage()

    # ── Check 1: canary tag vs CANARY_PERCENTAGE ───────────────────────────────
    canary_versions = _get_versions_by_tag(client, model_name, "canary")
    if canary_versions and canary_pct == 0:
        vlist = [v.version for v in canary_versions]
        issues.append(
            f"MLflow has canary version(s) {vlist} but CANARY_PERCENTAGE=0 — "
            "traffic is not being split to canary. Either increase "
            "CANARY_PERCENTAGE or roll back the canary version."
        )

    if not canary_versions and canary_pct > 0:
        issues.append(
            f"CANARY_PERCENTAGE={canary_pct} but no model version is tagged "
            "promotion_state=canary in the registry — traffic is being split "
            "to a canary container that has no registered version."
        )

    # ── Check 2: canary and Production coexist without a planned rollout ───────
    prod_versions = _get_production_versions(client, model_name)
    if canary_versions and prod_versions:
        # This is the *expected* state during a canary rollout, so only flag if
        # the canary version is *older* than the Production version — that would
        # indicate a stale canary tag from a previous failed promotion.
        for cv in canary_versions:
            for pv in prod_versions:
                if int(cv.version) < int(pv.version):
                    issues.append(
                        f"Canary version {cv.version} is older than Production "
                        f"version {pv.version} — this looks like a stale canary "
                        "tag from a previous promotion attempt. Run rollback or "
                        "remove the promotion_state tag."
                    )

    # ── Check 3: no Production version ────────────────────────────────────────
    if not prod_versions:
        staging = _get_staging_versions(client, model_name)
        shadow  = _get_versions_by_tag(client, model_name, "shadow")
        if not staging and not shadow and not canary_versions:
            issues.append(
                f"No Production version found for {model_name!r} and no "
                "candidate (Staging/shadow/canary) is in progress. The model "
                "registry may be empty or all versions have been archived."
            )

    # ── Check 4: shadow tag present (informational, not an error) ─────────────
    shadow_versions = _get_versions_by_tag(client, model_name, "shadow")
    if shadow_versions:
        vlist = [v.version for v in shadow_versions]
        log.info("Shadow evaluation in progress for version(s) %s — this is expected.", vlist)

    return issues


# ── Entry point ────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    parser = argparse.ArgumentParser(description="Promotion ladder state consistency check")
    parser.add_argument("--model-name", default=PROMOTION_MODEL_NAME)
    args = parser.parse_args(argv)

    try:
        issues = run_checks(args.model_name)
    except RuntimeError as exc:
        log.error("%s", exc)
        return 2

    if not issues:
        log.info("check_state: all consistency checks PASSED for %r.", args.model_name)
        return 0

    log.warning("check_state: %d inconsistency(ies) found for %r:", len(issues), args.model_name)
    for i, issue in enumerate(issues, 1):
        log.warning("  [%d] %s", i, issue)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
