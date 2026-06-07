"""Tracking experiment runner — STUB.

Detection fixed at rtdetr-x conf=0.3. Logs comparison + tuning runs to the
`tracking` MLflow experiment, each on BOTH clips (run = tracker × video, Gap 6).
See docs/MLFLOW_GUIDE.md §10.2 and §7 Step 7.

Comparison trackers : botsort, bytetrack, ocsort, strongsort
Tuning              : botsort @ match_thresh {0.6, 0.8, 0.9}  → tag result=no_effect if flat
BoT-SORT defaults (from services/iep2_vision/tracker/tracker.py):
  track_buffer=15, match_thresh=0.8, new_track_thresh=0.7, track_high_thresh=0.6,
  cmc_method=sof, frame_rate=5, with_reid=False
"""
from __future__ import annotations

from mlflow_utils import log_run  # noqa: F401

VIDEOS = {
    "mannequin": "testing-data/clip_mannequin.mp4",
    "crowded":   "testing-data/clip_cashier.mp4",
}

COMPARISON_TRACKERS = ["botsort", "bytetrack", "ocsort", "strongsort"]
TUNING_MATCH_THRESH = [0.6, 0.8, 0.9]   # botsort


def evaluate_tracking(tracker: str, match_thresh: float, video: str) -> tuple[dict, int]:
    """TODO: run rtdetr-x detections through `tracker` over EVERY frame of `video`
    (process to completion — Gap 1). Reuse services/iep2_vision/tracker/tracker.py.
    Return (metrics_dict, frames_processed) with the §5.2 programmable metrics
    (unique_track_ids, id_switches, peak_count, per_frame_assoc_ms, throughput_fps)."""
    raise NotImplementedError("Implement via the Claude Code prompt in §7 Step 7.")


def main() -> None:
    raise NotImplementedError(
        "Implement: loop COMPARISON_TRACKERS (phase=comparison) and "
        "TUNING_MATCH_THRESH (phase=tuning, botsort), each over both VIDEOS; "
        "log_run(experiment='tracking', ...). If the match_thresh sweep is flat, "
        "set tag result=no_effect on those runs."
    )


if __name__ == "__main__":
    main()
