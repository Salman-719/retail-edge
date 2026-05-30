"""Single-frame vision pipeline: detect -> track -> preprocess -> project.

Thin orchestrator tying the M2 plugins together for one frame. M3 wraps identity
logic around it; M4 wraps batch + persistence around that. The embedder is
intentionally NOT called here -- embeddings are collected by the identity layer
(M3) per the InitEmbeddings/SampleEmbeddings rules, not on every detection.
"""

from __future__ import annotations

from dataclasses import dataclass

from common.contracts.geometry import BBox, FloorPosition
from services.iep2_vision.app.vision.preprocess import filter_low_quality, suppress_duplicates
from services.iep2_vision.app.vision.tracker import TrackerOutput


@dataclass
class FrameDetection:
    """Fully processed detection for one person in one frame -- the output of
    the M2 vision layer, consumed by M3's identity layer."""

    track_id: int
    bbox: BBox
    confidence: float
    floor_pos: FloorPosition | None
    zone_id: str | None


class VisionPipeline:
    def __init__(self, detector, tracker, projector, settings, tracker_factory=None):
        self._detector = detector
        self._tracker = tracker
        self._projector = projector
        self._s = settings
        # Optional zero-arg callable that builds a fresh tracker. Supplied by the
        # runtime (config-built path) so a long camera outage can reset stale
        # Kalman state; absent when a tracker is injected (tests) -> reset no-ops.
        self._tracker_factory = tracker_factory

    def reset_tracker(self) -> bool:
        """Rebuild the tracker from its factory (fresh state after a long outage).
        Returns True if a reset happened, False when no factory is available."""
        if self._tracker_factory is None:
            return False
        self._tracker = self._tracker_factory()
        return True

    def process_frame(self, frame) -> tuple[list[FrameDetection], TrackerOutput, dict]:
        detections = self._detector.detect(frame)
        tracker_out = self._tracker.update(detections, frame)  # always called

        all_tracks = tracker_out.confirmed + tracker_out.new
        all_tracks, n_dup = suppress_duplicates(
            all_tracks, self._s.duplicate_iou_threshold, self._s.duplicate_containment_threshold
        )
        all_tracks, n_lowq = filter_low_quality(
            all_tracks,
            frame.shape[:2],
            self._s.min_detection_height_ratio,
            self._s.min_detection_aspect_ratio,
        )

        out: list[FrameDetection] = []
        for t in all_tracks:
            pos = self._projector.project(t.bbox)
            zone = self._projector.zone_of(pos) if pos else None
            out.append(FrameDetection(t.track_id, t.bbox, t.confidence, pos, zone))

        metrics = {"suppressed_duplicates": n_dup, "filtered_low_quality": n_lowq}
        return out, tracker_out, metrics
