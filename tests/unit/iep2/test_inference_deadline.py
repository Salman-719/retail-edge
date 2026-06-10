"""IEP2 inference-deadline + pending-leak tests.

Covers the YoloClient/ReidClient deadline behaviour: a stalled inference service
must never hang the camera — detect() falls back to [], extract() to None — and
no timed-out request may ever leak in _pending. See
specs/robustness-qa/iep2-vision/01-inference-zmq-deadline.md.
"""
import asyncio

import numpy as np
import pytest

import detector.detector as detector
import reid.reid as reid

pytestmark = pytest.mark.asyncio

_FRAME = np.zeros((16, 16, 3), dtype=np.uint8)
_DET = [{"label": "person", "confidence": 0.9, "bbox": [0.0, 0.0, 4.0, 8.0]}]


async def _resolve_pending(client, mapping, *, after=0.005):
    """Resolve some of the client's pending futures after a short delay.

    `mapping` is a function(list_of_(req_id, future)) -> None that sets results
    on whichever futures it wants; the rest are left to time out.
    """
    await asyncio.sleep(after)
    mapping(list(client._pending.items()))


# ── detect() single-call path ─────────────────────────────────────────────────

async def test_detect_returns_empty_on_timeout(yolo_client, monkeypatch):
    monkeypatch.setattr(detector, "YOLO_REQUEST_TIMEOUT_S", 0.05)
    result = await yolo_client.detect(_FRAME, 123)
    assert result == []
    assert yolo_client._timeouts == 1


async def test_detect_no_pending_leak_on_timeout(yolo_client, monkeypatch):
    monkeypatch.setattr(detector, "YOLO_REQUEST_TIMEOUT_S", 0.05)
    await yolo_client.detect(_FRAME, 123)
    assert yolo_client._pending == {}


async def test_detect_success_unaffected(yolo_client, monkeypatch):
    monkeypatch.setattr(detector, "YOLO_REQUEST_TIMEOUT_S", 1.0)

    async def _reply():
        await _resolve_pending(
            yolo_client, lambda items: items[0][1].set_result(_DET)
        )

    task = asyncio.create_task(_reply())
    result = await yolo_client.detect(_FRAME, 123)
    await task

    assert result == _DET
    assert yolo_client._timeouts == 0
    assert yolo_client._pending == {}


# ── detect_batch() path ───────────────────────────────────────────────────────

async def test_detect_batch_partial_timeout(yolo_client, monkeypatch):
    monkeypatch.setattr(detector, "YOLO_REQUEST_TIMEOUT_S", 0.1)
    monkeypatch.setattr(detector, "YOLO_BATCH_PER_FRAME_S", 0.0)

    frames = [_FRAME, _FRAME, _FRAME]
    ts = [1, 2, 3]

    def _reply(items):
        # Resolve the first and third dispatched frames; leave the middle hanging.
        items[0][1].set_result(_DET)
        items[2][1].set_result(_DET)

    task = asyncio.create_task(_resolve_pending(yolo_client, _reply, after=0.01))
    results = await yolo_client.detect_batch(frames, ts)
    await task

    assert len(results) == 3
    assert results[0] == _DET
    assert results[1] == []        # timed out → empty fallback
    assert results[2] == _DET
    assert yolo_client._timeouts == 1
    assert yolo_client._pending == {}


async def test_detect_batch_all_succeed_no_false_timeout(yolo_client, monkeypatch):
    monkeypatch.setattr(detector, "YOLO_REQUEST_TIMEOUT_S", 0.2)
    monkeypatch.setattr(detector, "YOLO_BATCH_PER_FRAME_S", 0.05)

    frames = [_FRAME] * 5
    ts = list(range(5))

    def _reply(items):
        for _rid, fut in items:
            if not fut.done():
                fut.set_result(_DET)

    task = asyncio.create_task(_resolve_pending(yolo_client, _reply, after=0.01))
    results = await yolo_client.detect_batch(frames, ts)
    await task

    assert results == [_DET] * 5
    assert yolo_client._timeouts == 0
    assert yolo_client._pending == {}


# ── extract() path (ReID) ─────────────────────────────────────────────────────

async def test_extract_returns_none_on_timeout(reid_client, monkeypatch):
    monkeypatch.setattr(reid, "REID_REQUEST_TIMEOUT_S", 0.05)
    result = await reid_client.extract(_FRAME, [0, 0, 8, 12], track_id=1, timestamp_ms=100)
    assert result is None
    assert reid_client._timeouts == 1
    assert reid_client._pending == {}


async def test_extract_success_unaffected(reid_client, monkeypatch):
    monkeypatch.setattr(reid, "REID_REQUEST_TIMEOUT_S", 1.0)
    emb = np.ones(reid.EMBEDDING_DIM, dtype=np.float32)

    async def _reply():
        await _resolve_pending(
            reid_client, lambda items: items[0][1].set_result(emb)
        )

    task = asyncio.create_task(_reply())
    result = await reid_client.extract(_FRAME, [0, 0, 8, 12], track_id=1, timestamp_ms=100)
    await task

    assert result is emb
    assert reid_client._timeouts == 0
    assert reid_client._pending == {}
