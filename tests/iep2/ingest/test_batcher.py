"""Batcher grouping (pure, no video)."""

from __future__ import annotations

import numpy as np

from services.iep2_vision.app.ingest.batcher import Batcher
from services.iep2_vision.app.ingest.video_source import SampledFrame


def _frames(n: int) -> list[SampledFrame]:
    blank = np.zeros((2, 2, 3), dtype=np.uint8)
    return [SampledFrame(frame=blank, timestamp_ms=i * 200, frame_index=i) for i in range(n)]


def test_groups_into_full_batches_plus_final_partial():
    # batch_window_seconds=1, target_fps=3 -> 3 frames per batch
    batches = list(Batcher(_frames(7), batch_window_seconds=1, target_fps=3))
    assert [bn for bn, _ in batches] == [0, 1, 2]
    assert [len(f) for _, f in batches] == [3, 3, 1]


def test_exact_multiple_no_trailing_partial():
    batches = list(Batcher(_frames(6), batch_window_seconds=1, target_fps=3))
    assert [len(f) for _, f in batches] == [3, 3]


def test_empty_source_yields_nothing():
    assert list(Batcher([], batch_window_seconds=1, target_fps=3)) == []
