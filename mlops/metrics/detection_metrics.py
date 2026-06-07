"""Detection metrics — pure functions. See docs/MLFLOW_GUIDE.md §5.1.

Programmable (no ground truth): computed from per-frame detection output.
Ground-truth (need labels): peak_count_error, mean_per_frame_count_error.

NOTE: `count_error` (|unique_tracks - total_people|) was removed — it counted
cumulative track IDs (a tracking-fragmentation signal: e.g. 43 tracks for 16
people), not detection/counting quality. People-count accuracy uses
`peak_count_error` (a per-frame detection metric) instead.
"""
from __future__ import annotations


def peak_count_error(peak_detected: int, peak_people_gt: int) -> int:
    """Phase-1 labeled metric: |max simultaneous detected - ground-truth peak|.

    Ground truth: clip_cashier peak_people=14. 0 means the model captured the
    busiest moment exactly; large positive = it missed people in the crowd."""
    return abs(peak_detected - peak_people_gt)


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


# ── False-positive clips (0 real people): every detection is a false positive ────
# Applies to any scene with total_people == 0 — mannequins, a printed hand-ad, etc.

def false_positive_per_frame(total_fp_detections: int, frames_processed: int) -> float:
    """Normalized false-positive rate: total FP detections / frames.

    The headline on a 0-people clip is the raw `false_positive_total` count, but it
    only compares fairly across runs that processed the same number of frames. This
    per-frame companion stays comparable even if frame counts differ (Gap 1 safety
    net). Lower is better; 0.0 = perfect rejection. rtdetr-x should approach 0 on
    mannequins (structural rejection) but may still fail on the printed hand-ad."""
    if frames_processed <= 0:
        return 0.0
    return total_fp_detections / frames_processed


def fp_object_rejection_rate(distinct_fp_objects_detected: int, fp_object_count: int) -> float:
    """OPTIONAL graded metric (only if you can attribute detections to distinct FP
    objects): 1 - detected/total. 1.0 = rejected all; 0.0 = detected all.

    e.g. fp_object_count = 8 mannequins, or 1 hand-ad. Not required for the headline
    (total-FP) approach, but informative if cheap to compute."""
    if fp_object_count <= 0:
        return 1.0
    return 1.0 - (distinct_fp_objects_detected / fp_object_count)


# ── Programmable metrics derived from harness FrameStats ────────────────────────

def programmable_metrics(stats) -> dict:
    """Convert raw harness FrameStats into the §5.1 programmable metric dict
    (no ground truth needed).

    `peak_detections_per_frame` = max RAW detections in any single frame (detector
    stage) — the detection-stage people-count signal. `id_switches` / `drop_to_zero`
    come from the tracker that runs in the same pass and are kept by choice as
    tracking-quality context, but they are tracking metrics, not detection ones.
    """
    confs = stats.confidences
    areas = stats.bbox_areas
    counts = stats.per_frame_counts
    return {
        "peak_detections_per_frame": max(counts) if counts else 0,
        "avg_confidence":            (sum(confs) / len(confs) * 100.0) if confs else 0.0,
        "avg_bbox_area":             (sum(areas) / len(areas)) if areas else 0.0,
        "id_switches":               stats.id_switches,        # tracker metric (kept by choice)
        "drop_to_zero":              sum(1 for c in counts if c == 0),
        "total_detections":          stats.total_detections,
        "frames_processed":          stats.frames_processed,
    }
    # NOTE: `unique_tracks` (cumulative distinct track IDs) and `count_error`
    # (|unique_tracks - total_people|) were dropped — they conflated tracking
    # fragmentation with detection/counting quality (e.g. 43 tracks for 16 people).
    # People-count accuracy is gated via `peak_count_error` instead.
