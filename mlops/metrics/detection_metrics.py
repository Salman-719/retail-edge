"""Detection metrics — pure functions. See docs/MLFLOW_GUIDE.md §5.1.

Programmable (no ground truth): computed from per-frame detection output.
Ground-truth (need labels): count_error, mean_per_frame_count_error.
"""
from __future__ import annotations


def count_error(unique_people_detected: int, total_people_gt: int) -> int:
    """Phase-1 labeled metric: |detected distinct people - ground-truth total|.

    0 means the run found exactly the right number of distinct people.
    """
    return abs(unique_people_detected - total_people_gt)


def mean_per_frame_count_error(per_frame_detected: dict[int, int],
                               per_frame_gt: dict[str, int]) -> float:
    """Phase-2 labeled metric: mean absolute error of per-frame people counts
    over the sampled, labeled frames. Frames without a label are skipped."""
    errors = []
    for frame_str, gt in per_frame_gt.items():
        idx = int(frame_str)
        if idx in per_frame_detected:
            errors.append(abs(per_frame_detected[idx] - gt))
    return sum(errors) / len(errors) if errors else 0.0


# TODO: programmable metrics (unique_people, peak_count, avg_confidence,
# avg_bbox_area, id_switches, drop_to_zero, mannequin_false_positives) are computed
# inside the eval harness from per-frame detector output — implement via §7 Step 4.
