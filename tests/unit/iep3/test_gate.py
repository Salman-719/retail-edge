"""
Tests for cross_camera_gate — pure spatial-temporal plausibility filter.
Invariant: never rejects simultaneous observations (elapsed <= 0).
"""
import pytest
from app.reid.gates import cross_camera_gate


def test_simultaneous_always_passes():
    """elapsed_s = 0 — gate passes (cannot exclude on timing alone)."""
    assert cross_camera_gate(10.0, 5.0, 1000, 10.0, 5.0, 1000, 1.5) is True


def test_negative_elapsed_always_passes():
    """new_ts < last_ts — elapsed_s < 0 — gate passes."""
    assert cross_camera_gate(0.0, 0.0, 500, 0.0, 0.0, 1000, 1.5) is True


def test_zero_distance_always_passes():
    """Same position, any elapsed — distance=0, speed=0 ≤ limit."""
    assert cross_camera_gate(5.0, 3.0, 2000, 5.0, 3.0, 1000, 1.5) is True


def test_within_speed_limit_passes():
    """1m in 1s at 1.5 m/s limit — passes."""
    assert cross_camera_gate(1.0, 0.0, 2000, 0.0, 0.0, 1000, 1.5) is True


def test_at_exact_speed_limit_passes():
    """1.5m in 1s at 1.5 m/s limit — passes (≤ not <)."""
    assert cross_camera_gate(1.5, 0.0, 2000, 0.0, 0.0, 1000, 1.5) is True


def test_above_speed_limit_fails():
    """2m in 1s at 1.5 m/s limit — fails."""
    assert cross_camera_gate(2.0, 0.0, 2000, 0.0, 0.0, 1000, 1.5) is False


def test_diagonal_movement():
    """3-4-5 triangle: 5m in 2s = 2.5 m/s > 1.5 limit — fails."""
    assert cross_camera_gate(3.0, 4.0, 3000, 0.0, 0.0, 1000, 1.5) is False


def test_slow_long_distance_passes():
    """10m in 10s = 1.0 m/s < 1.5 limit — passes."""
    assert cross_camera_gate(10.0, 0.0, 11_000, 0.0, 0.0, 1000, 1.5) is True
