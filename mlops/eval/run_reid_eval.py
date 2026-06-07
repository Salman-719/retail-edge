"""ReID experiment runner — STUB.

Detection + tracking fixed (rtdetr-x + BoT-SORT defaults). Logs comparison + tuning
runs to the `reid` MLflow experiment, each on BOTH clips (run = model × video, Gap 6).
See docs/MLFLOW_GUIDE.md §10.3 and §7 Step 8.

Comparison models : resnet50_msmt17, osnet_x1_0_msmt17, osnet_x1_0_market1501,
                    osnet_x1_0 (imagenet baseline = "wrong weights" control)
Tuning            : chosen model @ reid_threshold {0.75, 0.80, 0.85, 0.90}
EMBEDDING_DIM from services/iep2_vision/reid/reid.py = 2048 (resnet50); osnet = 512.
"""
from __future__ import annotations

from mlflow_utils import log_run  # noqa: F401

VIDEOS = {
    "mannequin": "testing-data/clip_mannequin.mp4",
    "crowded":   "testing-data/clip_cashier.mp4",
}

COMPARISON_MODELS = [
    {"reid_model": "resnet50_msmt17",       "weights": "resnet50_msmt17.pt",       "dataset": "msmt17",     "dim": 2048},
    {"reid_model": "osnet_x1_0_msmt17",     "weights": "osnet_x1_0_msmt17.pt",     "dataset": "msmt17",     "dim": 512},
    {"reid_model": "osnet_x1_0_market1501", "weights": "osnet_x1_0_market1501.pt", "dataset": "market1501", "dim": 512},
    {"reid_model": "osnet_x1_0",            "weights": "osnet_x1_0.pt",            "dataset": "imagenet",   "dim": 512},
]
TUNING_THRESHOLD = [0.75, 0.80, 0.85, 0.90]   # chosen model (start: resnet50_msmt17)


def evaluate_reid(weights: str, reid_threshold: float, video: str) -> tuple[dict, int]:
    """TODO: run the full det+track+reid path over EVERY frame of `video`
    (process to completion — Gap 1). Reuse services/iep2_vision/reid/reid.py.
    Return (metrics_dict, frames_processed) with the §5.3 programmable metrics
    (id_switches, unique_people, reid_match_rate, reid_false_merge_rate) and emit a
    similarity-score distribution plot to log as an artifact."""
    raise NotImplementedError("Implement via the Claude Code prompt in §7 Step 8.")


def main() -> None:
    raise NotImplementedError(
        "Implement: loop COMPARISON_MODELS (phase=comparison) and TUNING_THRESHOLD "
        "(phase=tuning, chosen model), each over both VIDEOS; "
        "log_run(experiment='reid', ...) with tags phase/scene/metric_type=proxy."
    )


if __name__ == "__main__":
    main()
