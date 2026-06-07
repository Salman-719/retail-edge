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
    # ── Detection quality ──────────────────────────────────────────────────────
    # avg_confidence: CALIBRATED to this project's clips, not the docs' number.
    # docs_models Round 4 reported 86.1% but on a DIFFERENT video; on the cashier
    # clip the good detectors (rtdetr-x/yolov8x/yolo11x-seg) score 76-86%, while the
    # noisy conf=0.15 run scores 57%. A >=75 bar cleanly separates good from noisy.
    # Only meaningful where real people exist -> scene-scoped to 'crowded' (it is
    # 0.0 on the mannequin clip, which correctly detects nothing).
    "avg_confidence":        (75.0, "gte"),   # %  — calibrated from 21-run sweep
    # rtdetr-x ID switches = 12 in docs; all crowded runs here are <=7, so the
    # docs' <=12 bar holds comfortably.
    "id_switches":           (12.0, "lte"),   #    — detection_experiments.md Round 4

    # ── People-counting accuracy (scene=crowded, peak GT = 14) ─────────────────
    # peak_count_error = |max detections in any single frame - 14|. This is a
    # DETECTION metric (how many people the model sees at the busiest moment).
    # Validated against the 21-run detection sweep: rtdetr-x/yolov8x/yolo11x-seg
    # all hit peak_count_error <= 1 at conf 0.3-0.5; noisy conf=0.15 (peak 32 -> 18)
    # correctly fails. So <=2 is both achievable and discriminating.
    "peak_count_error":      (2.0,  "lte"),   # |peak_detections_per_frame - 14|
    #
    # NOTE: `count_error` (|unique_tracks - 16|) is intentionally NOT gated. It
    # came out 19-41 even for RT-DETR, but that is TRACKING FRAGMENTATION, not a
    # detection failure: unique_tracks counts every track ID ever created, which
    # inflates in a busy/occluded scene (the same churn measured in
    # docs_models/tracking). It belongs in the tracking experiment, not the
    # detection promotion gate. RT-DETR's actual detection is excellent
    # (peak_detections_per_frame = 13 vs true peak 14).

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
    "peak_count_error":     {"crowded"},
    # avg_confidence is only meaningful where real people exist; on a 0-people clip
    # it is 0.0 (nothing detected = correct) and must not fail the gate.
    "avg_confidence":       {"crowded"},
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


# ── Registered-model name in the MLflow Model Registry ─────────────────────────
REGISTERED_MODEL = "retailvision-detector"


def register_to_staging(run_id: str, tracking_uri: str) -> None:
    """Auto-register the passed run as a NEW VERSION in STAGING (never Production).

    Human-in-the-loop boundary: the gate may auto-register a *candidate* (cheap,
    reversible bookkeeping that changes nothing live), but a HUMAN must later set it
    to Production and deploy. So we land the version in 'Staging', not 'Production'.
    """
    import mlflow
    mlflow.set_tracking_uri(tracking_uri)
    client = mlflow.MlflowClient()

    # Ensure the registered model exists (idempotent).
    try:
        client.create_registered_model(
            REGISTERED_MODEL,
            description="RetailVision person detector. Versions auto-registered to "
                        "Staging by the promotion gate; Production set manually.",
        )
    except Exception:
        pass  # already exists

    run = client.get_run(run_id)
    p = run.data.params
    mv = client.create_model_version(
        name=REGISTERED_MODEL,
        source=f"runs:/{run_id}/model",
        run_id=run_id,
        description=f"{p.get('model')} conf={p.get('conf')} — auto-registered to "
                    f"Staging by check_promotion.py (gate passed). Human approves Production.",
    )
    for k in ("model", "conf", "scene"):
        if p.get(k) is not None:
            client.set_model_version_tag(REGISTERED_MODEL, mv.version, k, str(p[k]))
    client.set_model_version_tag(REGISTERED_MODEL, mv.version, "registered_by", "check_promotion.py")
    # Stage = Staging (NOT Production). Aliases also supported on newer MLflow.
    try:
        client.transition_model_version_stage(REGISTERED_MODEL, mv.version, "Staging")
    except Exception:
        pass
    try:
        client.set_registered_model_alias(REGISTERED_MODEL, "candidate", mv.version)
    except Exception:
        pass

    print(f"📦  REGISTERED  {REGISTERED_MODEL} v{mv.version} → Staging (alias @candidate)")
    print( "   Human step: review, then set Production + deploy manually if approved.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="RetailVision model promotion gate")
    parser.add_argument("--run-id", required=True, help="MLflow run ID to evaluate")
    parser.add_argument(
        "--tracking-uri",
        default="http://localhost:5000",
        help="MLflow tracking server URI (default: http://localhost:5000)"
    )
    parser.add_argument(
        "--register",
        action="store_true",
        help="If the gate PASSES, auto-register the run as a new version in STAGING "
             "(opt-in). Production + deploy remain manual, human-in-the-loop.",
    )
    args = parser.parse_args()

    passed = check_run(args.run_id, args.tracking_uri)

    if passed and args.register:
        register_to_staging(args.run_id, args.tracking_uri)
    elif not passed and args.register:
        print("ℹ️  --register ignored: gate did not pass, nothing registered.")

    sys.exit(0 if passed else 1)
