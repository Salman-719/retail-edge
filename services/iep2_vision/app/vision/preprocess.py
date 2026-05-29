"""Detection preprocessing: duplicate suppression + low-quality filtering.

Runs after the tracker and before embedding to reduce ghost tracks and
low-quality crops that would poison the gallery. (Heuristics ported from the
current IEP2 runner.)
"""

from __future__ import annotations

from common.contracts.detection import TrackedDetection
from common.contracts.geometry import BBox


def _intersection_area(a: BBox, b: BBox) -> float:
    x1, y1 = max(a.x1, b.x1), max(a.y1, b.y1)
    x2, y2 = min(a.x2, b.x2), min(a.y2, b.y2)
    return max(0.0, x2 - x1) * max(0.0, y2 - y1)


def suppress_duplicates(
    dets: list[TrackedDetection], iou_thresh: float, containment_thresh: float
) -> tuple[list[TrackedDetection], int]:
    """Remove near-duplicate boxes (two tracks on one person). For each pair
    i<j (sorted by track_id), drop j if IoU(i,j) >= iou_thresh, or if j is
    largely contained in i and substantially smaller."""
    ordered = sorted(dets, key=lambda d: d.track_id)
    removed: set[int] = set()
    suppressed = 0
    for i in range(len(ordered)):
        if ordered[i].track_id in removed:
            continue
        for j in range(i + 1, len(ordered)):
            if ordered[j].track_id in removed:
                continue
            a, b = ordered[i].bbox, ordered[j].bbox
            inter = _intersection_area(a, b)
            if inter == 0:
                continue
            iou = inter / (a.area + b.area - inter) if (a.area + b.area - inter) > 0 else 0.0
            contain_j = inter / b.area if b.area > 0 else 0.0
            if iou >= iou_thresh or (contain_j >= containment_thresh and b.area <= 0.85 * a.area):
                removed.add(ordered[j].track_id)
                suppressed += 1
    kept = [d for d in ordered if d.track_id not in removed]
    return kept, suppressed


def filter_low_quality(
    dets: list[TrackedDetection],
    frame_shape: tuple[int, int],
    min_height_ratio: float,
    min_aspect_ratio: float,
) -> tuple[list[TrackedDetection], int]:
    """Drop boxes too small or wrongly proportioned to be a usable person crop:
    height/frame_height >= min_height_ratio AND height/width >= min_aspect_ratio."""
    frame_h = frame_shape[0]
    kept: list[TrackedDetection] = []
    filtered = 0
    for d in dets:
        h, w = d.bbox.height, max(d.bbox.width, 1e-6)
        if (h / frame_h) >= min_height_ratio and (h / w) >= min_aspect_ratio:
            kept.append(d)
        else:
            filtered += 1
    return kept, filtered
