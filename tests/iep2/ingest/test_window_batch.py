"""WindowBatch pure helpers (sync; no event loop)."""

from __future__ import annotations

from services.iep2_vision.app.ingest.redis_stream_source import RedisStreamFrameSource, WindowBatch


def test_ts_from_key():
    assert RedisStreamFrameSource._ts_from_key("frames/cam_01/1717075391200.jpg") == 1717075391200


def test_is_empty():
    assert WindowBatch(0, 0, 1, "offline", 300, 0, [], []).is_empty is True
    assert WindowBatch(0, 0, 1, "online", 300, 0, [], []).is_empty is True  # no keys
    assert WindowBatch(0, 0, 1, "online", 300, 1, ["frames/cam1/1.jpg"], []).is_empty is False
