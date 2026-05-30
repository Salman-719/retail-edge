"""A short gap rides over with no special code: because IEP2 only feeds the
tracker delivered frames (it never synthesizes empty updates for a gap), the
tracker's miss counter doesn't advance during the gap, so the next delivered
frame re-associates by IoU and the track keeps its ID. The spatial gate, which
uses real timestamps, separately sees the true elapsed time."""

from __future__ import annotations

import numpy as np

from common.contracts.detection import Detection
from common.contracts.geometry import BBox
from services.iep2_vision.app.identity.gates import spatial_temporal_gate
from services.iep2_vision.app.vision.tracker import IouTracker


def _det(x, conf=0.9):
    return Detection(bbox=BBox(x, 50, x + 40, 250), confidence=conf)


def test_track_survives_a_gap_because_no_empty_updates():
    t = IouTracker(min_hits=2, max_age=30, track_thresh=0.3, match_thresh=0.3)
    img = np.zeros((300, 400, 3), np.uint8)
    t.update([_det(100)], img)
    out = t.update([_det(103)], img)  # confirms
    tid = out.new[0].track_id

    # A 4s gap: IEP2 delivers no frames, so the tracker is simply NOT called.
    # The next delivered frame (slightly moved) re-associates to the same track.
    out = t.update([_det(110)], img)
    assert out.confirmed and out.confirmed[0].track_id == tid
    assert out.lost_track_ids == []


def test_gate_sees_true_elapsed_across_the_gap():
    # Same person, ~0.5 m apart, 4s elapsed -> plausible (accept).
    assert spatial_temporal_gate(0.5, 0.0, 5000, 0.0, 0.0, 1000, max_speed_mps=1.5) is True
    # Teleport 40 m in the same 4s -> implausible (reject). Index-derived stamps
    # that collapsed the gap would have wrongly accepted this.
    assert spatial_temporal_gate(40.0, 0.0, 5000, 0.0, 0.0, 1000, max_speed_mps=1.5) is False
