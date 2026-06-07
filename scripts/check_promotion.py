#!/usr/bin/env python3
"""
Model promotion gate for RetailVision.
Usage: python scripts/check_promotion.py --run-id <mlflow_run_id>
       python scripts/check_promotion.py --run-id <mlflow_run_id> --tracking-uri http://localhost:5000

The thresholds below are derived from the REAL benchmark results in docs_models/
(detection_experiments.md, tracking_experiments.md, reid_experiments.md) and use
the EXACT metric keys that the MLflow eval scripts in mlops/ actually log
(see mlops/metrics/detection_metrics.py and mlops/eval/run_detection_eval.py).

IMPORTANT — metrics that DO NOT exist in this codebase are intentionally NOT used.
The docs_models/ experiments never measured mAP, FPS, inference latency (ms),
ReID Rank-1 accuracy, precision/recall, or false-merge rate — those were
aspirational placeholders in MLOPS_PIPELINE.md, not real benchmarks. Using them
here would mean every run reports "MISSING". Only the metrics actually logged by
the eval pipeline are gated.
"""

from __future__ import annotations   # allow `str | None` hints on Python 3.9

import argparse
import sys

# Force UTF-8 stdout so the ✅/❌/⚠️/≥ glyphs print on Windows (cp1252) consoles too.
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

import mlflow

# ── Promotion thresholds ──────────────────────────────────────────────────────
# Derived from benchmark results in docs_models/
# Each entry: "mlflow_metric_name": (threshold_value, "gte" or "lte")
# "gte" = value must be >= threshold (higher is better, e.g. confidence)
# "lte" = value must be <= threshold (lower is better, e.g. id_switches)
#
# Source of each value (the winning model in each module's experiments):
#   detection winner = rtdetr-x  (docs_models/detection/detection_experiments.md Round 4 / Final Config)
#   tracking  winner = BoT-SORT  (docs_models/tracking/tracking_experiments.md  Round 1)
#
# NOTE on scene applicability: `false_positive_total` is only meaningful on the
# 0-people clips (scene=mannequin / scene=hand_ad). On the people-counting clip
# (scene=crowded) `count_error` / `peak_count_error` apply instead. The gate
# checks whichever of these the run actually logged and skips the others — a
# crowded-scene run is NOT failed for lacking false_positive_total, and vice
# versa. See _applicable_thresholds() below.
THRESHOLDS = {
    # ── Detection quality (rtdetr-x benchmark, docs_models/detection) ──────────
    # rtdetr-x avg confidence = 86.1% (vs yolov8x 81.4%). Promote only if a run
    # is at least as confident as the locked-in detector.
    "avg_confidence":        (86.0, "gte"),   # %  — detection_experiments.md Round 4
    # rtdetr-x ID switches = 12 (vs yolov8x 16). Fewer = more stable identities.
    "id_switches":           (12.0, "lte"),   #    — detection_experiments.md Round 4

    # ── People-counting accuracy (scene=crowded, GT=16 people / peak 14) ───────
    # ⚠️ TEAM: verify this tolerance against your labelled cashier clip results.
    # No ground-truth count error is recorded in docs_models/ (Phase-1 labelling
    # post-dates those docs), so this is an ESTIMATE: allow ±2 people / ±2 peak.
    "count_error":           (2.0,  "lte"),   # |detected - 16|  (estimate)
    "peak_count_error":      (2.0,  "lte"),   # |peak    - 14|   (estimate)

    # ── False-positive rejection (scene=mannequin / hand_ad, 0 real people) ────
    # rtdetr-x detected ZERO mannequins (perfect rejection) in Round 4. The
    # promotion bar is "no false positives" on a 0-people clip.
    # ⚠️ TEAM: rtdetr-x rejects 3-D mannequins but NOT the 2-D printed hand-ad
    # (detection_experiments Case 3). If gating a hand_ad run, this WILL fail by
    # design — set per-scene expectations before promoting on that clip.
    "false_positive_total":  (0.0,  "lte"),   #    — detection_experiments.md Round 4
}

# ── Optional per-scene applicability ──────────────────────────────────────────
# A metric is only checked if it was logged in the run. We additionally avoid
# failing a run for a metric that does not apply to its scene.
_SCENE_ONLY = {
    "false_positive_total": {"mannequin", "hand_ad"},
    "count_error":          {"crowded"},
    "peak_count_error":     {"crowded"},
}


def _applicable(metric_name: str, scene: str | None) -> bool:
    """True if this metric applies to the run's scene (or has no scene restriction)."""
    allowed = _SCENE_ONLY.get(metric_name)
    if allowed is None:
        return True            # scene-independent metric (e.g. avg_confidence)
    if scene is None:
        return True            # unknown scene → check it anyway, let MISSING handle it
    return scene in allowed


def check_run(run_id: str, tracking_uri: str) -> bool:
    mlflow.set_tracking_uri(tracking_uri)
    client = mlflow.MlflowClient()

    try:
        run = client.get_run(run_id)
    except Exception as e:
        print(f"❌ Could not fetch run {run_id}: {e}")
        sys.exit(1)

    metrics = run.data.metrics
    params = run.data.params
    scene = run.data.tags.get("scene") or params.get("scene")

    print(f"\n{'='*60}")
    print(f"Run ID:   {run_id}")
    print(f"Run name: {run.info.run_name or 'unnamed'}")
    print(f"Scene:    {scene or 'unknown'}")
    print(f"{'='*60}\n")

    all_passed = True
    for metric_name, (threshold, direction) in THRESHOLDS.items():
        if not _applicable(metric_name, scene):
            print(f"➖ SKIP    {metric_name}: not applicable to scene '{scene}'")
            continue

        value = metrics.get(metric_name)

        if value is None:
            print(f"⚠️  MISSING  {metric_name}: not logged in this run")
            all_passed = False
            continue

        if direction == "gte":
            passed = value >= threshold
            symbol = "≥"
        else:
            passed = value <= threshold
            symbol = "≤"

        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{status}  {metric_name}: {value:.4f} (must be {symbol} {threshold})")

        if not passed:
            all_passed = False

    print(f"\n{'='*60}")
    if all_passed:
        print("✅  PROMOTE — all applicable thresholds passed")
        print("   Next step: update model reference in services/iep2_vision/ and services/iep3_reconciliation/")
    else:
        print("❌  DO NOT PROMOTE — one or more thresholds failed")
        print("   Re-run experiment with adjusted hyperparameters and try again")
    print(f"{'='*60}\n")

    return all_passed


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="RetailVision model promotion gate")
    parser.add_argument("--run-id", required=True, help="MLflow run ID to evaluate")
    parser.add_argument(
        "--tracking-uri",
        default="http://localhost:5000",
        help="MLflow tracking server URI (default: http://localhost:5000)"
    )
    args = parser.parse_args()

    passed = check_run(args.run_id, args.tracking_uri)
    sys.exit(0 if passed else 1)
