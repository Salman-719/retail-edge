"""Iep2Runtime.run_from_iep1: window-driven loop — online windows fetch+process
frames and emit batch_complete + ack; a run of offline windows triggers a tracker
reset; every window (incl. offline) advances the batch clock."""

from __future__ import annotations

from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from common.config import get_settings
from common.contracts.detection import Detection
from common.contracts.geometry import BBox
from services.iep2_vision.app.ingest.redis_stream_source import RedisStreamFrameSource, WindowBatch
from services.iep2_vision.app.runtime import Iep2Runtime
from services.iep2_vision.app.vision.tracker import IouTracker
from tests.fakes import FakeRedisStream, FakeS3
from tests.iep2.identity.helpers import FakePersistence, LabelEmbedder

pytestmark = pytest.mark.asyncio


class _CountingDetector:
    def __init__(self):
        self.frames_seen = 0

    def detect(self, frame):
        self.frames_seen += 1
        return [Detection(bbox=BBox(100, 50, 180, 250), confidence=0.9)]


class _RecordingEmitter:
    def __init__(self):
        self.emitted = []

    async def emit(self, store_id, camera_id, batch_number, window_start_ms, window_end_ms):
        self.emitted.append((camera_id, batch_number, window_start_ms, window_end_ms))

    async def close(self):
        pass


class _FakeSource:
    def __init__(self, batches, s3):
        self._batches = batches
        self._reader = RedisStreamFrameSource("cam1", s3_client=s3, redis_client=FakeRedisStream())
        self.acked = []

    async def windows(self):
        for i, b in enumerate(self._batches):
            yield b, f"id-{i}"

    async def fetch_frames(self, batch):
        async for item in self._reader.fetch_frames(batch):
            yield item

    async def ack(self, msg_id):
        self.acked.append(msg_id)


def _calibration():
    return SimpleNamespace(
        cam_id="cam1", homography=[1, 0, 0, 0, 1, 0, 0, 0, 1],
        zone_polygons={"zones": [{"zone_id": "A", "polygon": [[0, 0], [400, 0], [400, 300], [0, 300]]}]},
    )


async def _runtime(detector, events):
    rt = Iep2Runtime("store", "cam1", get_settings())
    await rt.setup(
        _calibration(),
        detector=detector,
        tracker=IouTracker(min_hits=3, max_age=30, track_thresh=0.5, match_thresh=0.5),
        embedder=LabelEmbedder(),
        persistence=FakePersistence(),
        events=events,
        warm_restart=False,
    )
    return rt


def _jpeg(label=120):
    return cv2.imencode(".jpg", np.full((300, 400, 3), label, dtype=np.uint8))[1].tobytes()


async def test_online_window_fetches_processes_emits_acks():
    s3 = FakeS3()
    await s3.put_bytes("frames/cam1/1000.jpg", _jpeg())
    await s3.put_bytes("frames/cam1/1200.jpg", _jpeg())
    batch = WindowBatch(0, 0, 60_000, "online", 300, 2,
                        ["frames/cam1/1000.jpg", "frames/cam1/1200.jpg"], [])
    det, events = _CountingDetector(), _RecordingEmitter()
    rt = await _runtime(det, events)
    source = _FakeSource([batch], s3)

    await rt.run_from_iep1(source)

    assert det.frames_seen == 2                 # both S3 frames processed
    assert events.emitted == [("cam1", 0, 0, 60_000)]
    assert source.acked == ["id-0"]             # acked after success


async def test_offline_windows_emit_and_eventually_reset_tracker():
    s3 = FakeS3()
    n = get_settings().offline_reset_windows
    batches = [WindowBatch(i, i * 60_000, (i + 1) * 60_000, "offline", 300, 0, [], [])
               for i in range(n)]
    det, events = _CountingDetector(), _RecordingEmitter()
    rt = await _runtime(det, events)

    resets = []
    rt._pipeline.reset_tracker = lambda: resets.append(1)  # spy
    source = _FakeSource(batches, s3)

    await rt.run_from_iep1(source)

    assert det.frames_seen == 0                  # no frames in offline windows
    assert [e[1] for e in events.emitted] == list(range(n))  # every window emits, monotonic
    assert len(source.acked) == n               # all acked
    assert len(resets) == 1                      # reset fired once at the threshold
