"""Tracking metrics — pure functions. See docs/MLFLOW_GUIDE.md §5.2.

Primary programmable metric: unique_track_ids (lower = less identity churn).
Ground-truth metric: fragmentation = unique_track_ids / total_people_gt.
"""
from __future__ import annotations


def fragmentation(unique_track_ids: int, total_people_gt: int) -> float:
    """Phase-1 labeled metric: track IDs created per real person.

    1.0 = perfect (one track per person). >1 = over-segmentation.
    e.g. BoT-SORT 29 / 12 people = 2.42  vs  StrongSORT 54 / 12 = 4.50.
    """
    if total_people_gt <= 0:
        raise ValueError("total_people_gt must be > 0")
    return unique_track_ids / total_people_gt


# TODO: programmable metrics (unique_track_ids, id_switches, peak_count,
# drop_to_zero, per_frame_assoc_ms, throughput_fps) are computed inside the eval
# harness from the tracker output — implement via §7 Step 4 / Step 7.
