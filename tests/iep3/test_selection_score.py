"""Position-selection scoring (pure)."""

from __future__ import annotations

import pytest

from services.iep3_reconciliation.app.selection import selection_score


def test_weighted_combination():
    # area normalized by frame pixels, weighted 0.7; confidence weighted 0.3
    score = selection_score(bbox_area=5000, confidence=0.8, frame_pixels=10000, w_area=0.7, w_conf=0.3)
    assert score == pytest.approx(0.7 * 0.5 + 0.3 * 0.8)


def test_zero_frame_pixels_safe():
    assert selection_score(5000, 0.8, 0, 0.7, 0.3) == pytest.approx(0.3 * 0.8)


def test_larger_closer_box_scores_higher():
    big = selection_score(9000, 0.7, 10000, 0.7, 0.3)
    small = selection_score(1000, 0.7, 10000, 0.7, 0.3)
    assert big > small
