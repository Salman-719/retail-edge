"""ReID experiment runner.

Detection + tracking FIXED (rtdetr-x conf0.5 + BoT-SORT). Varies the ReID model and
the cosine recovery threshold. Runs on the CROWDED clip only (need real people who
disappear/reappear). Logs to the `reid` MLflow experiment.

⚠️ PROXY METRICS ONLY — no per-person identity ground truth exists for the clip, so
true match/false-merge accuracy cannot be computed. See mlops/metrics/reid_metrics.py.

Comparison models (core 4, from reid_experiments.md candidate table):
  osnet_x1_0        (ImageNet baseline — wrong weights, expected worst)
  osnet_x1_0_msmt17 (OSNet, MSMT17 — "current best")
  osnet_x1_0_market1501 (OSNet, Market-1501 — retail-like)
  resnet50_msmt17   (ResNet-50, MSMT17 — heavier, 2048-dim; the deployed model)
Threshold sweep (chosen model): reid_threshold {0.75, 0.80, 0.85, 0.90}

Run:
  export MLFLOW_TRACKING_URI=http://localhost:5000
  python mlops/eval/run_reid_eval.py            # all reid runs
  python mlops/eval/run_reid_eval.py --smoke    # 1 model, quick check
"""
from __future__ import annotations

import argparse
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_MLOPS = os.path.dirname(_HERE)
sys.path.insert(0, _MLOPS)

from mlflow_utils import run_context, log_metrics_params_artifacts
from harness import run_reid_clip
from metrics import reid_metrics as rm

SEED = 42
_CLIPS_DIR = os.environ.get("CLIPS_DIR", "testing-data")
CROWDED_CLIP = os.path.join(_CLIPS_DIR, "clip_cashier.mp4")
SCENE = "crowded"

# ImageNet baseline osnet_x1_0 intentionally EXCLUDED — boxmot has no ReID-trained
# URL for the bare name; only ReID-trained models are compared.
COMPARISON_MODELS = [
    {"model": "osnet_x1_0_msmt17",     "weights": "osnet_x1_0_msmt17.pt",     "dataset": "msmt17",     "dim": 512},
    {"model": "osnet_x1_0_market1501", "weights": "osnet_x1_0_market1501.pt", "dataset": "market1501", "dim": 512},
    {"model": "resnet50_msmt17",       "weights": "resnet50_msmt17.pt",       "dataset": "msmt17",     "dim": 2048},
]
TUNING_THRESHOLD = [0.75, 0.80, 0.85, 0.90]
TUNING_MODEL = {"model": "resnet50_msmt17", "weights": "resnet50_msmt17.pt", "dataset": "msmt17", "dim": 2048}

DEFAULT_THRESHOLD = 0.85
_LABELS_PATH = os.path.join(_MLOPS, "labeling", "labels.json")
_OUT_DIR = os.path.join(_MLOPS, "outputs")


def _total_people() -> int:
    with open(_LABELS_PATH) as f:
        return json.load(f).get(os.path.basename(CROWDED_CLIP), {}).get("total_people")


def _save_results_json(prefix: str, params: dict, metrics: dict) -> str:
    os.makedirs(_OUT_DIR, exist_ok=True)
    p = os.path.join(_OUT_DIR, f"{prefix}_results.json")
    with open(p, "w") as f:
        json.dump({"params": params, "metrics": metrics}, f, indent=2)
    return p


def _save_similarity_hist(attempt_sims, threshold, prefix) -> str | None:
    """Histogram of cosine similarities at every recovery attempt, with the
    threshold line. A discriminative model is bimodal (clear gap at the threshold);
    an untrained one bunches in the middle."""
    if not attempt_sims:
        return None
    import matplotlib; matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    os.makedirs(_OUT_DIR, exist_ok=True)
    plt.figure(figsize=(6, 4))
    plt.hist(attempt_sims, bins=20, range=(0.0, 1.0), edgecolor="black")
    plt.axvline(threshold, color="red", linestyle="--", label=f"threshold {threshold}")
    plt.xlabel("recovery cosine similarity"); plt.ylabel("attempts")
    plt.title(f"{prefix} — recovery similarity distribution"); plt.legend()
    plt.tight_layout()
    out = os.path.join(_OUT_DIR, f"{prefix}_sim_hist.png")
    plt.savefig(out, dpi=100); plt.close()
    return out


def _save_recovery_montage(recovery_pairs, prefix) -> str | None:
    """Grid of gallery-crop vs recovered-crop for accepted recoveries — visual proof
    of whether a recovery matched the same person (the only correctness spot-check
    possible without identity ground truth). Uniform person-shaped tiles, a clear
    'GALLERY | RECOVERED' header, and a sim label per pair."""
    if not recovery_pairs:
        return None
    import cv2, numpy as np
    os.makedirs(_OUT_DIR, exist_ok=True)

    TW, TH = 96, 192          # uniform tile (person aspect ratio), W x H
    GAP, LBL, HDR = 8, 22, 26
    WHITE = (255, 255, 255)

    def _tile(img):
        return cv2.resize(img, (TW, TH))

    pair_w = TW * 2 + GAP
    rows = []
    for gal, new, sim in recovery_pairs:
        canvas = np.full((TH + LBL, pair_w, 3), 255, np.uint8)
        canvas[0:TH, 0:TW] = _tile(gal)
        canvas[0:TH, TW + GAP:TW + GAP + TW] = _tile(new)
        cv2.putText(canvas, f"sim {sim:.2f}", (2, TH + LBL - 6),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 130, 0), 1)
        rows.append(canvas)

    # Lay pairs in a grid: up to 4 per row.
    per_row = 4
    grid_rows = []
    for i in range(0, len(rows), per_row):
        chunk = rows[i:i + per_row]
        while len(chunk) < per_row:
            chunk.append(np.full_like(rows[0], 255))
        grid_rows.append(np.hstack([np.hstack([c, np.full((c.shape[0], GAP, 3), 255, np.uint8)]) for c in chunk]))
    body = np.vstack([np.vstack([g, np.full((GAP, g.shape[1], 3), 255, np.uint8)]) for g in grid_rows])

    header = np.full((HDR, body.shape[1], 3), 255, np.uint8)
    cv2.putText(header, "recovery pairs:  GALLERY (lost) | RECOVERED (new)  -- same person?",
                (4, HDR - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)
    montage = np.vstack([header, body])

    out = os.path.join(_OUT_DIR, f"{prefix}_recovery_montage.png")
    cv2.imwrite(out, montage)
    return out


def run_one(model: str, weights: str, dataset: str, threshold: float, phase: str) -> None:
    total_people = _total_people()
    prefix = f"{model}_thr{threshold}_{SCENE}"
    params = {"reid_model": model, "weights": weights, "weights_dataset": dataset,
              "reid_threshold": threshold, "detector": "rtdetr-x", "det_conf": 0.5,
              "tracker": "botsort", "video": os.path.basename(CROWDED_CLIP),
              "scene": SCENE, "total_people": total_people}

    with run_context("reid", prefix):
        stats = run_reid_clip(reid_weights=weights, video_path=CROWDED_CLIP,
                              reid_threshold=threshold, conf=0.5, seed=SEED)
        metrics = rm.programmable_metrics(stats, total_people)
        artifacts = [_save_results_json(prefix, params, metrics)]
        hist = _save_similarity_hist(stats.attempt_sims, threshold, prefix)
        if hist:
            artifacts.append(hist)
        montage = _save_recovery_montage(stats.recovery_pairs, prefix)
        if montage:
            artifacts.append(montage)
        log_metrics_params_artifacts(
            params=params, metrics=metrics,
            tags={"phase": phase, "scene": SCENE, "metric_type": "reid_proxy"},
            artifacts=artifacts, seed=SEED,
        )
    print(f"[logged] {prefix}  unique_local_ids={metrics['unique_local_ids']} "
          f"count_err={metrics['count_error']} "
          f"match_rate={metrics['reid_match_rate']:.2f} "
          f"recoveries={metrics['reid_recoveries']}/{metrics['reid_attempts']}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true", help="one model, quick check")
    args = ap.parse_args()

    if args.smoke:
        run_one("resnet50_msmt17", "resnet50_msmt17.pt", "msmt17", DEFAULT_THRESHOLD, "comparison")
        return

    # Fault-tolerant: one model failing is logged + skipped, not fatal to the batch.
    def _safe(model, weights, dataset, thr, phase):
        try:
            run_one(model, weights, dataset, thr, phase)
        except Exception as e:
            print(f"[SKIPPED] {model} thr{thr} {phase} -> {type(e).__name__}: {str(e)[:120]}")

    # Comparison: 4 models at the default threshold
    for m in COMPARISON_MODELS:
        _safe(m["model"], m["weights"], m["dataset"], DEFAULT_THRESHOLD, "comparison")

    # Tuning: chosen model across thresholds
    for thr in TUNING_THRESHOLD:
        _safe(TUNING_MODEL["model"], TUNING_MODEL["weights"], TUNING_MODEL["dataset"], thr, "tuning")


if __name__ == "__main__":
    main()
