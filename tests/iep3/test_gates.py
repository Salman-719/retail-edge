"""Cross-camera gate (pure)."""

from __future__ import annotations

from services.iep3_reconciliation.app.reid.gates import cross_camera_gate


def test_plausible_cross_camera_move_passes():
    assert cross_camera_gate(1.0, 0.0, 1000, 0.0, 0.0, 0, max_speed_mps=1.5) is True


def test_teleport_fails():
    assert cross_camera_gate(100.0, 0.0, 1000, 0.0, 0.0, 0, max_speed_mps=1.5) is False


def test_zero_or_negative_elapsed_accepts():
    assert cross_camera_gate(9.0, 9.0, 1000, 0.0, 0.0, 1000, max_speed_mps=1.5) is True
    assert cross_camera_gate(9.0, 9.0, 500, 0.0, 0.0, 1000, max_speed_mps=1.5) is True
