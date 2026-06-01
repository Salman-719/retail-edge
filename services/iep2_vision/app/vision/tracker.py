"""Tracker plugin: protocol + lifecycle-aware output + implementations + factory.

The spec's source-of-truth tracker is ByteTrack (motion-only), with BoT-SORT as
an appearance-aided upgrade -- both wrap boxmot and are selected by config. For
environments without the heavy tracking stack (CI, CPU dev, the descriptor
fallback path), an `IouTracker` provides a real, dependency-free motion tracker
with identical lifecycle semantics. All implementations share one protocol.

Design invariant (spec M2 review issue B2): `update` is ALWAYS called, even with
an empty detection list, so ages/lost counters advance and lost tracks are
reported. The per-frame pipeline must never short-circuit on empty detections.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import numpy as np

from common.contracts.detection import Detection, TrackedDetection
from common.contracts.geometry import BBox


@dataclass
class TrackerOutput:
    """Per-frame result, split by track lifecycle state."""

    confirmed: list[TrackedDetection]  # established tracks with stable IDs
    new: list[TrackedDetection]  # tracks confirmed this frame (need a Local ID)
    lost_track_ids: list[int]  # confirmed tracks dropped this frame


class Tracker(Protocol):
    def update(self, detections: list[Detection], frame: np.ndarray) -> TrackerOutput:
        """Advance the tracker by one frame. Must be called every frame, even
        when detections is empty."""
        ...


def _iou(a: BBox, b: BBox) -> float:
    ix1, iy1 = max(a.x1, b.x1), max(a.y1, b.y1)
    ix2, iy2 = min(a.x2, b.x2), min(a.y2, b.y2)
    inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    if inter <= 0:
        return 0.0
    return inter / (a.area + b.area - inter)


class _Track:
    __slots__ = ("track_id", "bbox", "score", "hits", "misses", "confirmed")

    def __init__(self, track_id: int, bbox: BBox, score: float):
        self.track_id = track_id
        self.bbox = bbox
        self.score = score
        self.hits = 1
        self.misses = 0
        self.confirmed = False


class IouTracker:
    """Dependency-free, deterministic motion tracker (greedy IoU association).

    Continuous for the process lifetime -- never reset between batches. A track
    confirms after `min_hits` consecutive associations and is dropped after
    `max_age` consecutive misses; only confirmed tracks are emitted, and a track
    is reported `lost` exactly once when a confirmed track is dropped.
    """

    def __init__(self, min_hits: int, max_age: int, track_thresh: float, match_thresh: float):
        self._min_hits = max(1, min_hits)
        self._max_age = max_age
        self._track_thresh = track_thresh
        self._match_thresh = match_thresh
        self._tracks: dict[int, _Track] = {}
        self._next_id = 1

    def update(self, detections: list[Detection], frame: np.ndarray | None = None) -> TrackerOutput:
        dets = [d for d in detections if d.confidence >= self._track_thresh]

        # --- greedy IoU association (highest IoU first) ---
        pairs: list[tuple[float, int, int]] = []
        track_ids = list(self._tracks)
        for ti, tid in enumerate(track_ids):
            for di, det in enumerate(dets):
                iou = _iou(self._tracks[tid].bbox, det.bbox)
                if iou >= self._match_thresh:
                    pairs.append((iou, tid, di))
        pairs.sort(key=lambda p: p[0], reverse=True)

        matched_tracks: set[int] = set()
        matched_dets: set[int] = set()
        for _iou_val, tid, di in pairs:
            if tid in matched_tracks or di in matched_dets:
                continue
            matched_tracks.add(tid)
            matched_dets.add(di)
            t = self._tracks[tid]
            t.bbox = dets[di].bbox
            t.score = dets[di].confidence
            t.hits += 1
            t.misses = 0

        confirmed: list[TrackedDetection] = []
        new: list[TrackedDetection] = []

        # matched tracks: emit as new (just confirmed) or confirmed (already was)
        for tid in matched_tracks:
            t = self._tracks[tid]
            if not t.confirmed and t.hits >= self._min_hits:
                t.confirmed = True
                new.append(TrackedDetection(t.track_id, t.bbox, t.score))
            elif t.confirmed:
                confirmed.append(TrackedDetection(t.track_id, t.bbox, t.score))

        # unmatched detections -> new tracks (may confirm immediately if min_hits==1)
        for di, det in enumerate(dets):
            if di in matched_dets:
                continue
            t = _Track(self._next_id, det.bbox, det.confidence)
            self._next_id += 1
            self._tracks[t.track_id] = t
            if t.hits >= self._min_hits:
                t.confirmed = True
                new.append(TrackedDetection(t.track_id, t.bbox, t.score))

        # unmatched tracks -> age; drop (and report lost if confirmed) past max_age
        lost: list[int] = []
        for tid in track_ids:
            if tid in matched_tracks:
                continue
            t = self._tracks[tid]
            t.misses += 1
            if t.misses > self._max_age:
                if t.confirmed:
                    lost.append(tid)
                del self._tracks[tid]

        return TrackerOutput(confirmed=confirmed, new=new, lost_track_ids=lost)


class ByteTrackTracker:
    """Motion-only ByteTrack via boxmot. Continuous for the process lifetime."""

    def __init__(self, min_hits: int, max_age: int, track_thresh: float, match_thresh: float):
        from boxmot.trackers.bytetrack.bytetrack import ByteTrack  # heavy dep; imported lazily

        self._tracker = ByteTrack(
            min_hits=min_hits,
            track_thresh=track_thresh,
            match_thresh=match_thresh,
            track_buffer=max_age,
        )
        self._min_hits = min_hits
        self._known_ids: set[int] = set()

    def update(self, detections: list[Detection], frame: np.ndarray) -> TrackerOutput:
        dets = np.array(
            [[d.bbox.x1, d.bbox.y1, d.bbox.x2, d.bbox.y2, d.confidence, 0] for d in detections],
            dtype=np.float32,
        ).reshape(-1, 6)
        online = self._tracker.update(dets, frame)  # advances state even if empty

        confirmed, new, active_ids = [], [], set()
        for row in online:
            x1, y1, x2, y2, tid = float(row[0]), float(row[1]), float(row[2]), float(row[3]), int(row[4])
            score = float(row[5]) if len(row) > 5 else 1.0
            td = TrackedDetection(tid, BBox(x1, y1, x2, y2), score)
            active_ids.add(tid)
            if tid not in self._known_ids:
                new.append(td)
                self._known_ids.add(tid)
            else:
                confirmed.append(td)

        lost = list(self._known_ids - active_ids)
        self._known_ids -= set(lost)
        return TrackerOutput(confirmed=confirmed, new=new, lost_track_ids=lost)


class BotSortTracker(ByteTrackTracker):
    """Appearance-aided BoT-SORT via boxmot (upgrade path). Same protocol."""

    def __init__(self, min_hits: int, max_age: int, track_thresh: float, match_thresh: float):
        from boxmot.reid.core.reid import ReID
        from boxmot.trackers.botsort.botsort import BotSort

        reid_model = ReID(device="cpu", half=False).model
        self._tracker = BotSort(
            reid_model=reid_model,
            min_hits=min_hits,
            track_high_thresh=track_thresh,
            track_low_thresh=min(0.1, track_thresh),
            new_track_thresh=track_thresh,
            match_thresh=match_thresh,
            track_buffer=max_age,
            with_reid=True,
        )
        self._min_hits = min_hits
        self._known_ids = set()


def create_tracker(backend: str, **kwargs) -> Tracker:
    if backend == "iou":
        return IouTracker(**kwargs)
    if backend == "bytetrack":
        return ByteTrackTracker(**kwargs)
    if backend == "botsort":
        return BotSortTracker(**kwargs)
    raise ValueError(f"unknown tracker backend: {backend}")
