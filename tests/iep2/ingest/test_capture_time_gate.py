"""Capture-time end-to-end: timestamps parsed from S3 keys feed the spatial gate,
proving index-derived stamps are gone (IEP2 amendment §9)."""

from __future__ import annotations

from services.iep2_vision.app.identity.gates import spatial_temporal_gate
from services.iep2_vision.app.ingest.redis_stream_source import RedisStreamFrameSource


def test_keys_4s_apart_drive_the_gate():
    ts_a = RedisStreamFrameSource._ts_from_key("frames/cam1/1717075380000.jpg")
    ts_b = RedisStreamFrameSource._ts_from_key("frames/cam1/1717075384000.jpg")
    assert ts_b - ts_a == 4000  # real 4s gap recovered from the keys

    # plausible walk over the real elapsed time -> accept
    assert spatial_temporal_gate(1.0, 0.0, ts_b, 0.0, 0.0, ts_a, max_speed_mps=1.5) is True
    # teleport over the same real elapsed time -> reject
    assert spatial_temporal_gate(50.0, 0.0, ts_b, 0.0, 0.0, ts_a, max_speed_mps=1.5) is False
