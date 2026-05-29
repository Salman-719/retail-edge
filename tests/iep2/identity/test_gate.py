"""Spatial-temporal gate behaviour."""

from __future__ import annotations

from services.iep2_vision.app.identity.gates import spatial_temporal_gate


def test_plausible_move_passes():
    # 1 m in 1 s at 1.5 m/s budget -> ok
    assert spatial_temporal_gate(1.0, 0.0, 1000, 0.0, 0.0, 0, max_speed_mps=1.5) is True


def test_teleport_fails():
    # 100 m in 1 s -> impossible
    assert spatial_temporal_gate(100.0, 0.0, 1000, 0.0, 0.0, 0, max_speed_mps=1.5) is False


def test_zero_elapsed_accepts_without_crash():
    assert spatial_temporal_gate(5.0, 5.0, 1000, 0.0, 0.0, 1000, max_speed_mps=1.5) is True


def test_earlier_timestamp_accepts():
    assert spatial_temporal_gate(5.0, 5.0, 500, 0.0, 0.0, 1000, max_speed_mps=1.5) is True
