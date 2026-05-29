"""Metrics modules expose the required signals (incl. the ML-specific ones)."""

from __future__ import annotations

from prometheus_client import generate_latest

from services.iep2_vision.app import metrics as iep2_metrics
from services.iep3_reconciliation.app import metrics as iep3_metrics


def test_iep2_metrics_present():
    iep2_metrics.detection_confidence.labels("cam1").observe(0.9)  # ML signal
    iep2_metrics.active_tracks.labels("cam1").set(3)
    body = generate_latest(iep2_metrics.REGISTRY).decode()
    for name in ("iep2_frame_processing_seconds", "iep2_detections_per_frame",
                 "iep2_detection_confidence", "iep2_active_tracks", "iep2_lost_pool_size"):
        assert name in body


def test_iep3_metrics_present():
    iep3_metrics.global_links.labels(outcome="cross_camera").inc()
    iep3_metrics.match_similarity.observe(0.91)  # ML signal
    body = generate_latest(iep3_metrics.REGISTRY).decode()
    for name in ("iep3_batch_reconcile_seconds", "iep3_global_links_total",
                 "iep3_cross_camera_similarity", "iep3_positions_written_total"):
        assert name in body
