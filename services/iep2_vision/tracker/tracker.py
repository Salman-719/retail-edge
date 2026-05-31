"""Tracker — sole owner of ByteTrack state and update logic.

Swap ByteTrack for another tracker here and nothing outside this file changes.
Config values are named constants at the top; they must never be buried as
magic numbers inside the functions below.
"""
import sys

import numpy as np
import supervision as sv

# ByteTrack config — the only place these values are allowed to live.
LOST_TRACK_BUFFER = 15
MINIMUM_MATCHING_THRESHOLD = 0.7


def create_tracker() -> sv.ByteTrack:
    """Instantiate and return a fresh ByteTrack object.

    Caller owns the returned object. Create one per upload thread; discard
    when the thread ends so no state bleeds between uploads.

    Two extra attributes are attached for sequential ID remapping:
      _id_map      : dict mapping ByteTrack's internal IDs -> local 1-based IDs
      _next_local  : next available local ID
    """
    tracker = sv.ByteTrack(
        lost_track_buffer=LOST_TRACK_BUFFER,
        minimum_matching_threshold=MINIMUM_MATCHING_THRESHOLD,
    )
    tracker._id_map = {}
    tracker._next_local = 1
    return tracker


def update(tracker: sv.ByteTrack, detections: list[dict]) -> list[dict]:
    """Advance tracker state with the current frame's detections.

    Accepts our internal format: {label, confidence, bbox: [x1,y1,x2,y2]}.
    Tentative (unconfirmed) tracks are filtered out here — callers never see
    a None tracker_id.
    Returns confirmed tracks as list of
      {track_id, label, confidence, bbox: [x1,y1,x2,y2]}.
    """
    if not detections:
        # Still call update so the tracker can age out lost tracks.
        empty = sv.Detections.empty()
        tracker.update_with_detections(empty)
        return []

    bboxes = np.array([d["bbox"] for d in detections], dtype=float)   # (N,4) xyxy
    confs  = np.array([d["confidence"] for d in detections], dtype=float)
    # supervision expects class_id as int array for Detections
    class_ids = np.zeros(len(detections), dtype=int)

    sv_dets = sv.Detections(
        xyxy=bboxes,
        confidence=confs,
        class_id=class_ids,
    )

    tracked = tracker.update_with_detections(sv_dets)

    results: list[dict] = []
    for i, tid in enumerate(tracked.tracker_id):
        if tid is None:
            continue  # tentative — discard
        raw = int(tid)
        if raw not in tracker._id_map:
            tracker._id_map[raw] = tracker._next_local
            tracker._next_local += 1
        local_id = tracker._id_map[raw]
        label = detections[i]["label"] if i < len(detections) else "person"
        conf  = float(tracked.confidence[i]) if tracked.confidence is not None else 0.0
        x1, y1, x2, y2 = tracked.xyxy[i].tolist()
        results.append({
            "track_id": local_id,
            "label": label,
            "confidence": conf,
            "bbox": [x1, y1, x2, y2],
        })
    return results


# ---------------------------------------------------------------------------
# Standalone smoke test (rule 1): python tracker/tracker.py
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import json

    fake_detections = [
        {"label": "person", "confidence": 0.88, "bbox": [100.0, 150.0, 200.0, 400.0]},
        {"label": "person", "confidence": 0.76, "bbox": [300.0, 120.0, 420.0, 380.0]},
    ]

    t = create_tracker()
    # Run two frames so ByteTrack can confirm tracks.
    update(t, fake_detections)
    tracks = update(t, fake_detections)
    print(json.dumps(tracks, indent=2))
    print("smoke test passed" if isinstance(tracks, list) else "FAILED")
