"""VisionPipeline smoke test with stub detector + IoU tracker + identity proj.

Exercises detect -> track -> preprocess -> project on CPU with no weights, the
M2 exit criterion.
"""

from __future__ import annotations

import numpy as np

from common.config import get_settings
from common.contracts.detection import Detection
from common.contracts.geometry import BBox
from services.iep2_vision.app.vision.pipeline import FrameDetection, VisionPipeline
from services.iep2_vision.app.vision.projection import FloorProjector
from services.iep2_vision.app.vision.tracker import IouTracker


class _StubDetector:
    """Emits one walking person; ignores frame contents."""

    def __init__(self):
        self._x = 100.0

    def detect(self, frame) -> list[Detection]:
        self._x += 3.0
        return [Detection(bbox=BBox(self._x, 50, self._x + 50, 250), confidence=0.9)]


def test_pipeline_produces_frame_detections():
    settings = get_settings()
    projector = FloorProjector(np.eye(3), [{"zone_id": "A", "polygon": [[0, 0], [640, 0], [640, 480], [0, 480]]}],
                               (0.0, 0.0, 640.0, 480.0))
    tracker = IouTracker(min_hits=settings.bytetrack_min_hits, max_age=settings.bytetrack_max_age,
                         track_thresh=settings.bytetrack_track_thresh, match_thresh=0.3)
    pipeline = VisionPipeline(_StubDetector(), tracker, projector, settings)

    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    last_out: list[FrameDetection] = []
    for _ in range(6):
        out, tracker_out, metrics = pipeline.process_frame(frame)
        assert isinstance(out, list)
        assert "suppressed_duplicates" in metrics and "filtered_low_quality" in metrics
        last_out = out

    # by now the track is confirmed and projected to a floor position + zone
    assert len(last_out) == 1
    fd = last_out[0]
    assert isinstance(fd, FrameDetection)
    assert fd.floor_pos is not None
    assert fd.zone_id == "A"
