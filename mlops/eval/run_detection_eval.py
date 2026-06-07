"""Detection experiment runner (Path A: standalone Ultralytics/boxmot).

Logs comparison + tuning runs to the `detection` MLflow experiment, each on BOTH
clips (run = model × video, Gap 6). See docs/MLFLOW_GUIDE.md §10.1.

Comparison models : yolov8n, yolov8x, yolo11x-seg, rtdetr-x   (conf=0.3, imgsz=640)
Tuning            : rtdetr-x @ conf {0.15, 0.30, 0.50}
Each runs on      : clip_mannequin.mp4 (scene=mannequin), clip_cashier.mp4 (scene=crowded)

Ground truth (mlops/labeling/labels.json):
  clip_cashier   = 16 real people, peak 14 -> count_error, peak_count_error
  clip_mannequin = 0 people, 8 mannequins  -> every detection is a false positive
                   -> false_positive_total (graded headline) + false_positive_per_frame

Run:
  export MLFLOW_TRACKING_URI=http://localhost:5000
  python mlops/eval/run_detection_eval.py            # all runs
  python mlops/eval/run_detection_eval.py --smoke    # 1 model × 1 clip (quick check)
"""
from __future__ import annotations

import argparse
import json
import os
import sys

# Make sibling packages importable whether run as a module or a script.
_HERE = os.path.dirname(os.path.abspath(__file__))
_MLOPS = os.path.dirname(_HERE)
sys.path.insert(0, _MLOPS)

from mlflow_utils import run_context, log_metrics_params_artifacts
from harness import run_detection_clip
from metrics import detection_metrics as dm

# Clip directory is configurable so the same code runs on the host
# (CLIPS_DIR defaults to ./testing-data) and in the container (set to the
# mounted path, e.g. /workspace/testing-data).
_CLIPS_DIR = os.environ.get("CLIPS_DIR", "testing-data")
# scene -> clip filename. mannequin + hand_ad are both 0-people false-positive
# scenes; crowded is the people-counting scene.
VIDEOS = {
    "mannequin": os.path.join(_CLIPS_DIR, "clip_mannequin.mp4"),
    "hand_ad":   os.path.join(_CLIPS_DIR, "hand_on_ad_in_store.mp4"),
    "crowded":   os.path.join(_CLIPS_DIR, "clip_cashier.mp4"),
}

COMPARISON_MODELS = [
    {"model": "yolov8n",     "weights": "yolov8n.pt"},
    {"model": "yolov8x",     "weights": "yolov8x.pt"},
    {"model": "yolo11x-seg", "weights": "yolo11x-seg.pt"},
    {"model": "rtdetr-x",    "weights": "rtdetr-x.pt"},
]
TUNING_CONF = [0.15, 0.30, 0.50]   # rtdetr-x

_LABELS_PATH = os.path.join(_MLOPS, "labeling", "labels.json")
SEED = 42


def _labels() -> dict:
    with open(_LABELS_PATH) as f:
        return json.load(f)


def _labeled_metrics(scene: str, clip_key: str, base: dict, labels: dict) -> tuple[dict, str]:
    """Compute the GT metric appropriate to the clip; return (metrics, metric_type tag)."""
    gt = labels.get(clip_key, {})
    extra: dict = {}
    if gt.get("total_people", 0) and gt["total_people"] > 0:
        extra["count_error"] = dm.count_error(base["unique_tracks"], gt["total_people"])
        if gt.get("peak_people") is not None:
            extra["peak_count_error"] = dm.peak_count_error(
                base["peak_detections_per_frame"], gt["peak_people"])
        return extra, "labeled_count"
    # 0-people clip (mannequins, hand-ad, …): every detection is a false positive.
    if gt.get("total_people", None) == 0:
        extra["false_positive_total"] = base["total_detections"]
        extra["false_positive_per_frame"] = dm.false_positive_per_frame(
            base["total_detections"], base["frames_processed"])
        return extra, "labeled_fp"
    return extra, "proxy"


_OUT_DIR = os.path.join(_MLOPS, "outputs")


def _confidence_histogram(confidences, title: str, out_path: str) -> str | None:
    """Save a detection-confidence distribution PNG (mirrors detection_experiments
    Round 6). Returns the path, or None if there were no detections to plot."""
    if not confidences:
        return None
    import matplotlib
    matplotlib.use("Agg")  # headless — no display in the container
    import matplotlib.pyplot as plt
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    plt.figure(figsize=(6, 4))
    plt.hist(confidences, bins=20, range=(0.0, 1.0), edgecolor="black")
    plt.xlabel("detection confidence")
    plt.ylabel("count")
    plt.title(title)
    plt.tight_layout()
    plt.savefig(out_path, dpi=100)
    plt.close()
    return out_path


def _save_sample_frames(stats, prefix: str) -> list[str]:
    """Write annotated sample frames (boxes drawn) to PNGs. Returns their paths.
    These are the visual proof of false positives (a box on a mannequin / hand-ad)."""
    import cv2
    paths = []
    os.makedirs(_OUT_DIR, exist_ok=True)
    for idx, img in stats.sample_frames:
        p = os.path.join(_OUT_DIR, f"{prefix}_frame{idx}.png")
        if cv2.imwrite(p, img):
            paths.append(p)
    return paths


def _save_results_json(prefix: str, params: dict, metrics: dict, per_frame_counts) -> str:
    """Write a machine-readable record of the run (params + metrics + per-frame
    counts) so any table/plot can be regenerated without re-running."""
    os.makedirs(_OUT_DIR, exist_ok=True)
    p = os.path.join(_OUT_DIR, f"{prefix}_results.json")
    with open(p, "w") as f:
        json.dump({"params": params, "metrics": metrics,
                   "per_frame_counts": per_frame_counts}, f, indent=2)
    return p


def run_one(model: str, weights: str, conf: float, scene: str, phase: str, labels: dict) -> None:
    clip_path = VIDEOS[scene]
    clip_key = os.path.basename(clip_path)
    prefix = f"{model}_conf{conf}_{scene}"
    params = {"model": model, "weights": weights, "conf": conf, "imgsz": 640,
              "video": clip_key, "scene": scene,
              "total_people": labels.get(clip_key, {}).get("total_people"),
              "fp_object_count": labels.get(clip_key, {}).get("fp_object_count")}

    # Open the MLflow run FIRST, then run inference INSIDE it so the system-metrics
    # monitor samples CPU/RAM during the (long) inference. Doing inference before
    # opening the run records zero system metrics.
    with run_context("detection", prefix):
        stats = run_detection_clip(weights=weights, video_path=clip_path, conf=conf, seed=SEED)
        metrics = dm.programmable_metrics(stats)
        labeled, metric_type = _labeled_metrics(scene, clip_key, metrics, labels)
        metrics.update(labeled)

        artifacts = []
        hist = _confidence_histogram(stats.confidences,
                                     title=f"{prefix} — confidence distribution",
                                     out_path=os.path.join(_OUT_DIR, f"{prefix}_confhist.png"))
        if hist:
            artifacts.append(hist)
        artifacts += _save_sample_frames(stats, prefix)
        artifacts.append(_save_results_json(prefix, params, metrics, stats.per_frame_counts))

        log_metrics_params_artifacts(
            params=params,
            metrics=metrics,
            tags={"phase": phase, "scene": scene, "metric_type": metric_type},
            artifacts=artifacts,
            seed=SEED,
        )

    fp_or_err = (f"false_positive_total={metrics.get('false_positive_total')}"
                 if metric_type == "labeled_fp"
                 else f"count_err={metrics.get('count_error')}")
    print(f"[logged] {prefix}  unique_tracks={metrics['unique_tracks']}  {fp_or_err}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true", help="one model × one clip, quick check")
    args = ap.parse_args()
    labels = _labels()

    if args.smoke:
        # Light model on CPU so the wiring check finishes in seconds, not minutes.
        run_one("yolov8n", "yolov8n.pt", 0.30, "mannequin", "comparison", labels)
        return

    # Comparison: 4 models × 2 videos
    for m in COMPARISON_MODELS:
        for scene in VIDEOS:
            run_one(m["model"], m["weights"], 0.30, scene, "comparison", labels)

    # Tuning: rtdetr-x × conf sweep × 2 videos
    for conf in TUNING_CONF:
        for scene in VIDEOS:
            run_one("rtdetr-x", "rtdetr-x.pt", conf, scene, "tuning", labels)


if __name__ == "__main__":
    main()
