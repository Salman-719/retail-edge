"""Detection experiment runner — STUB.

Logs comparison + tuning runs to the `detection` MLflow experiment, each on BOTH
clips (run = model × video, Gap 6). See docs/MLFLOW_GUIDE.md §10.1 for the exact
run table and §7 Step 6 for the Claude Code prompt that fills this in.

Comparison models : yolov8n, yolov8x, yolo11x-seg, rtdetr-x   (conf=0.3, imgsz=640)
Tuning            : rtdetr-x @ conf {0.15, 0.30, 0.50}
Each runs on      : clip_mannequin.mp4 (scene=mannequin), clip_cashier.mp4 (scene=crowded)
"""
from __future__ import annotations

import os

from mlflow_utils import log_run  # noqa: F401 (used once implemented)

VIDEOS = {
    "mannequin": "testing-data/clip_mannequin.mp4",
    "crowded":   "testing-data/clip_cashier.mp4",
}

COMPARISON_MODELS = [
    {"model": "yolov8n",     "weights": "yolov8n.pt"},
    {"model": "yolov8x",     "weights": "yolov8x.pt"},
    {"model": "yolo11x-seg", "weights": "yolo11x-seg.pt"},
    {"model": "rtdetr-x",    "weights": "rtdetr-x.pt"},
]
TUNING_CONF = [0.15, 0.30, 0.50]   # rtdetr-x


def evaluate_detection(weights: str, conf: float, video: str) -> tuple[dict, int]:
    """TODO: run the detector over EVERY frame of `video` (process to completion —
    Gap 1, never stop on a timer). Reuse services/iep2_vision/detector/detector.py.
    Return (metrics_dict, frames_processed) with the §5.1 programmable metrics."""
    raise NotImplementedError("Implement via the Claude Code prompt in §7 Step 6.")


def main() -> None:
    raise NotImplementedError(
        "Implement: loop COMPARISON_MODELS (phase=comparison) and TUNING_CONF "
        "(phase=tuning), each over both VIDEOS, calling evaluate_detection() then "
        "log_run(experiment='detection', ...) with tags phase/scene/metric_type=proxy."
    )


if __name__ == "__main__":
    main()
