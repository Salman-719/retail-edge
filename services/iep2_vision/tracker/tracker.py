"""Tracker — sole owner of BoTSORT state and update logic.

Uses BoTSORT from boxmot 10.0.84 with the built-in ReID DISABLED (with_reid=False).
Association is motion-only: Kalman filter + IoU + camera-motion compensation (SOF).
Appearance ReID for cross-camera identity lives in the separate osnet-service and
LocalIdentityManager — BoTSORT must not duplicate it.

Swap BoTSORT for another tracker here and nothing outside this file changes.
Config values are named constants at the top; they must never be buried as
magic numbers inside the functions below.
"""
from pathlib import Path

import numpy as np
import torch
from boxmot import BoTSORT

# BoTSORT config — the only place these values are allowed to live.
TRACK_BUFFER        = 15
MATCH_THRESH        = 0.8
NEW_TRACK_THRESH    = 0.7
TRACK_HIGH_THRESH   = 0.6
FRAME_RATE          = 5


def create_tracker() -> BoTSORT:
    """Instantiate and return a fresh BoTSORT object (ReID disabled).

    Caller owns the returned object. Create one per upload thread; discard
    when the thread ends so no state bleeds between uploads.

    Two extra attributes are attached for sequential ID remapping:
      _id_map      : dict mapping BoTSORT's internal IDs -> local 1-based IDs
      _next_local  : next available local ID
    """
    tracker = BoTSORT(
        # with_reid=False, so BoTSORT never instantiates the appearance backend
        # and model_weights is never read — pass an empty path, no weights are
        # downloaded or loaded.
        model_weights=Path(""),
        device=torch.device("cpu"),
        fp16=False,
        track_buffer=TRACK_BUFFER,
        match_thresh=MATCH_THRESH,
        new_track_thresh=NEW_TRACK_THRESH,
        track_high_thresh=TRACK_HIGH_THRESH,
        with_reid=False,
        cmc_method="sof",
        frame_rate=FRAME_RATE,
    )
    tracker._id_map = {}
    tracker._next_local = 1
    return tracker


def update(tracker: BoTSORT, detections: list[dict], frame: np.ndarray) -> list[dict]:
    """Advance tracker state with the current frame's detections.

    Accepts our internal format: {label, confidence, bbox: [x1,y1,x2,y2]} plus the
    full BGR frame the detections came from. BoTSORT's CMC (sof) reads the frame
    to estimate camera motion, so it must be the real image, not a placeholder.
    Returns confirmed tracks as list of
      {track_id, label, confidence, bbox: [x1,y1,x2,y2]}.
    """
    if not detections:
        # Still call update so the tracker can age out lost tracks. CMC needs a
        # real frame even with no detections, so pass the frame through.
        empty = np.empty((0, 6), dtype=float)
        tracker.update(empty, frame)
        return []

    bboxes = np.array([d["bbox"] for d in detections], dtype=float)   # (N,4) xyxy
    confs  = np.array([d["confidence"] for d in detections], dtype=float)
    class_ids = np.zeros(len(detections), dtype=float)

    # boxmot expects [x1, y1, x2, y2, conf, class_id] per detection
    dets = np.concatenate([bboxes, confs[:, None], class_ids[:, None]], axis=1)  # (N,6)

    tracked = tracker.update(dets, frame)  # (M, [x1,y1,x2,y2,tid,conf,cls,...])

    results: list[dict] = []
    for row in tracked:
        tid = int(row[4])
        if tid not in tracker._id_map:
            tracker._id_map[tid] = tracker._next_local
            tracker._next_local += 1
        local_id = tracker._id_map[tid]
        x1, y1, x2, y2 = float(row[0]), float(row[1]), float(row[2]), float(row[3])
        conf = float(row[5]) if len(row) > 5 else 0.0
        results.append({
            "track_id": local_id,
            "label": "person",
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
    # CMC needs a real frame; a blank 640×480 image is enough for the smoke test.
    fake_frame = np.zeros((480, 640, 3), dtype=np.uint8)

    t = create_tracker()
    # Run two frames so BoTSORT can confirm tracks.
    update(t, fake_detections, fake_frame)
    tracks = update(t, fake_detections, fake_frame)
    print(json.dumps(tracks, indent=2))
    print("smoke test passed" if isinstance(tracks, list) else "FAILED")
