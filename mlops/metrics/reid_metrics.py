"""ReID metrics — pure functions. See docs/MLFLOW_GUIDE.md §5.3.

Primary programmable metric: id_switches (lower = better re-identification).
Ground-truth metric: count_error = |unique local_ids - total_people_gt|.
"""
from __future__ import annotations


def count_error(unique_local_ids: int, total_people_gt: int) -> int:
    """Phase-1 labeled metric: distinct local_ids vs ground-truth total people.

    0 means no false splits (too many ids) and no wrong merges (too few ids).
    """
    return abs(unique_local_ids - total_people_gt)


def reid_match_rate(successful_recoveries: int, total_lookups: int) -> float:
    """Programmable: fraction of ReID lookups that recovered a prior identity."""
    return successful_recoveries / total_lookups if total_lookups else 0.0


def reid_false_merge_rate(wrong_merges: int, total_recoveries: int) -> float:
    """Programmable (if gallery vs recovered identity is tracked):
    fraction of recoveries that wrongly merged two different people."""
    return wrong_merges / total_recoveries if total_recoveries else 0.0
