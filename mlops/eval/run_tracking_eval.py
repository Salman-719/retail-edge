"""Tracking experiment runner.

Detection FIXED at rtdetr-x conf=0.5 (the promoted detector). Varies the tracker.
Runs on the CROWDED clip only — tracking quality is only meaningful where there are
real moving people. Logs to the `tracking` MLflow experiment.

Comparison trackers : botsort, bytetrack, ocsort, strongsort
Tuning (botsort)    : match_thresh {0.6, 0.8, 0.9}  → tag result=no_effect if flat

Metrics (mlops/metrics/tracking_metrics.py), drop_to_zero excluded:
  Tier 1: id_switches, unique_track_ids, track_fragmentation (÷16)
  Tier 2: peak_confirmed_tracks, peak_track_error (vs 14), avg_track_lifetime
  Tier 3: per_frame_assoc_ms, throughput_fps   (tracker.update() only)

Run:
  export MLFLOW_TRACKING_URI=http://localhost:5000
  python mlops/eval/run_tracking_eval.py            # all tracking runs
  python mlops/eval/run_tracking_eval.py --smoke    # 1 tracker, quick check
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
from harness import run_detection_clip
from metrics import tracking_metrics as tm

# Detection is fixed — every tracker sees identical rtdetr-x conf0.5 boxes.
DET_WEIGHTS = "rtdetr-x.pt"
DET_CONF = 0.5
DET_IMGSZ = 640
SEED = 42

_CLIPS_DIR = os.environ.get("CLIPS_DIR", "testing-data")
CROWDED_CLIP = os.path.join(_CLIPS_DIR, "clip_cashier.mp4")
SCENE = "crowded"

COMPARISON_TRACKERS = ["botsort", "bytetrack", "ocsort", "strongsort"]
TUNING_MATCH_THRESH = [0.6, 0.8, 0.9]   # botsort

_LABELS_PATH = os.path.join(_MLOPS, "labeling", "labels.json")
_OUT_DIR = os.path.join(_MLOPS, "outputs")


def _gt() -> tuple[int, int]:
    """(total_people, peak_people) for the crowded clip from labels.json."""
    with open(_LABELS_PATH) as f:
        g = json.load(f).get(os.path.basename(CROWDED_CLIP), {})
    return g.get("total_people"), g.get("peak_people")


def _save_results_json(prefix: str, params: dict, metrics: dict) -> str:
    os.makedirs(_OUT_DIR, exist_ok=True)
    p = os.path.join(_OUT_DIR, f"{prefix}_results.json")
    with open(p, "w") as f:
        json.dump({"params": params, "metrics": metrics}, f, indent=2)
    return p


def _save_track_timeline(track_frames: dict, prefix: str, n_frames: int) -> str | None:
    """Track-timeline (Gantt) artifact: one horizontal bar per track ID over the
    frames it was alive. Visualizes tracker churn at a glance — a stable tracker
    shows few long bars; a churny one shows many short/fragmented bars."""
    if not track_frames:
        return None
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    os.makedirs(_OUT_DIR, exist_ok=True)
    # Order tracks by first appearance so the chart reads top-to-bottom over time.
    items = sorted(track_frames.items(), key=lambda kv: min(kv[1]))
    fig_h = max(3, min(20, 0.18 * len(items)))
    plt.figure(figsize=(10, fig_h))
    for row, (tid, frames) in enumerate(items):
        fs = sorted(frames)
        # draw contiguous segments so gaps (ID reused after vanishing) are visible
        seg_start = prev = fs[0]
        for f in fs[1:] + [None]:
            if f is None or f != prev + 1:
                plt.hlines(row, seg_start, prev, color="tab:blue", linewidth=2)
                if f is not None:
                    seg_start = f
            prev = f if f is not None else prev
    plt.xlabel("frame"); plt.ylabel("track (ordered by first appearance)")
    plt.title(f"{prefix} — track timeline ({len(items)} track IDs over {n_frames} frames)")
    plt.tight_layout()
    out = os.path.join(_OUT_DIR, f"{prefix}_track_timeline.png")
    plt.savefig(out, dpi=100); plt.close()
    return out


def run_one(tracker: str, match_thresh: float, phase: str) -> dict:
    total_people, peak_people = _gt()
    prefix = f"{tracker}_mt{match_thresh}_{SCENE}"
    params = {"tracker": tracker, "match_thresh": match_thresh,
              "detector": "rtdetr-x", "det_conf": DET_CONF, "imgsz": DET_IMGSZ,
              "video": os.path.basename(CROWDED_CLIP), "scene": SCENE,
              "with_reid": False, "total_people": total_people, "peak_people": peak_people}

    with run_context("tracking", prefix):
        stats = run_detection_clip(
            weights=DET_WEIGHTS, video_path=CROWDED_CLIP,
            conf=DET_CONF, imgsz=DET_IMGSZ,
            tracker_name=tracker, match_thresh=match_thresh, seed=SEED,
        )
        metrics = tm.programmable_metrics(stats, total_people, peak_people)
        artifacts = []
        # Track-timeline (Gantt) — the key tracking artifact: visualizes churn.
        timeline = _save_track_timeline(stats.track_frames, prefix, stats.frames_processed)
        if timeline:
            artifacts.append(timeline)
        # Peak frame kept too (detection-side context), but it's not the main one.
        if stats.peak_frame is not None:
            import cv2
            os.makedirs(_OUT_DIR, exist_ok=True)
            pidx, pcount, pimg = stats.peak_frame
            ppath = os.path.join(_OUT_DIR, f"{prefix}_PEAK_{pcount}det_frame{pidx}.png")
            if cv2.imwrite(ppath, pimg):
                artifacts.append(ppath)
        artifacts.append(_save_results_json(prefix, params, metrics))

        log_metrics_params_artifacts(
            params=params, metrics=metrics,
            tags={"phase": phase, "scene": SCENE, "metric_type": "tracking"},
            artifacts=artifacts, seed=SEED,
        )
    print(f"[logged] {prefix}  unique_track_ids={metrics['unique_track_ids']} "
          f"id_switches={metrics['id_switches']} "
          f"frag={metrics['track_fragmentation']:.2f} "
          f"assoc_ms={metrics['per_frame_assoc_ms']:.2f}")
    return metrics


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true", help="one tracker, quick check")
    args = ap.parse_args()

    if args.smoke:
        run_one("botsort", 0.8, "comparison")
        return

    # Comparison: 4 trackers (botsort uses its default match_thresh=0.8)
    for trk in COMPARISON_TRACKERS:
        run_one(trk, 0.8, "comparison")

    # Tuning: botsort match_thresh sweep
    for mt in TUNING_MATCH_THRESH:
        run_one("botsort", mt, "tuning")


if __name__ == "__main__":
    main()
