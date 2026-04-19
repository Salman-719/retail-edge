"""Unit tests for IEP service Pydantic schemas.

Each service has its own `app/schemas.py` under a sibling `services/iep*/`
package. Importing them via sys.path collides because they all live under the
same `app` package name — so we load each schemas module directly from its
file path with a unique module name instead.
"""
import importlib.util
import os
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[2]


def _load(service: str):
    """Load services/{service}/app/schemas.py as a standalone module."""
    path = ROOT / "services" / service / "app" / "schemas.py"
    mod_name = f"_schemas_{service.replace('-', '_')}"
    if mod_name in sys.modules:
        return sys.modules[mod_name]
    spec = importlib.util.spec_from_file_location(mod_name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def iep1():
    return _load("iep1-ingestion")


@pytest.fixture(scope="module")
def iep2():
    return _load("iep2-vision")


@pytest.fixture(scope="module")
def iep3():
    return _load("iep3-alerts")


@pytest.fixture(scope="module")
def iep4():
    return _load("iep4-analytics")


@pytest.fixture(scope="module")
def iep5():
    return _load("iep5-agent")


# ─── IEP1: Ingestion schemas ────────────────────────────────────────────────

class TestIEP1Schemas:
    def test_video_upload_response(self, iep1):
        r = iep1.VideoUploadResponse(
            camera_id="cam1",
            video_s3_key="stores/s1/cameras/cam1/video.mp4",
            video_fps=30.0,
            video_duration=120.5,
            video_width=1920,
            video_height=1080,
        )
        assert r.camera_id == "cam1"
        assert r.video_fps == 30.0

    def test_video_upload_response_missing_field(self, iep1):
        with pytest.raises(ValidationError):
            iep1.VideoUploadResponse(camera_id="cam1")


# ─── IEP2: Vision schemas ───────────────────────────────────────────────────

class TestIEP2Schemas:
    def test_tracking_start_request(self, iep2):
        req = iep2.TrackingStartRequest(
            video_s3_key="stores/s1/cameras/c1/video.mp4",
            homography_matrix=[[1, 0, 0], [0, 1, 0], [0, 0, 1]],
            zones=[{"name": "A", "points": [{"x": 0, "y": 0}]}],
            store_id="store1",
        )
        assert req.model_size == "yolov8n"
        assert req.pixels_per_meter == 100.0

    def test_tracking_progress_response(self, iep2):
        r = iep2.TrackingProgressResponse(
            status="running",
            progress=50,
            total_frames=1000,
        )
        assert r.zone_occupancy == {}
        assert r.error is None

    def test_zone_occupancy(self, iep2):
        zo = iep2.ZoneOccupancy(seconds=45.2, percent=23.1)
        assert zo.seconds == 45.2

    def test_trajectory_point(self, iep2):
        tp = iep2.TrajectoryPoint(frameIdx=100, x=3.5, y=7.2, trackId=5)
        assert tp.frameIdx == 100

    def test_trajectory_response_default_empty(self, iep2):
        r = iep2.TrajectoryResponse()
        assert r.trajectory == []


# ─── IEP3: Alerts schemas ───────────────────────────────────────────────────

class TestIEP3Schemas:
    def test_alert_rule_create(self, iep3):
        rule = iep3.AlertRuleCreate(
            store_id="store1",
            name="Queue too long",
            type="zone_crowding",
            zone_name="Checkout",
            threshold_count=10,
        )
        assert rule.enabled is True

    def test_tracking_event(self, iep3):
        evt = iep3.TrackingEvent(
            store_id="store1",
            camera_id="cam1",
            zone_occupancy={"Checkout": {"seconds": 30, "percent": 50}},
            trajectory=[],
            total_frames=1000,
            fps=30.0,
        )
        assert evt.store_id == "store1"
        assert evt.zone_occupancy["Checkout"].seconds == 30


# ─── IEP4: Analytics schemas ────────────────────────────────────────────────

class TestIEP4Schemas:
    def test_tracking_snapshot(self, iep4):
        snap = iep4.TrackingSnapshot(
            store_id="store1",
            camera_id="cam1",
            zone_occupancy={"A": {"seconds": 10, "percent": 50}},
            trajectory=[],
            total_frames=100,
            fps=30.0,
        )
        assert snap.recorded_at is None
        assert snap.zone_occupancy["A"].percent == 50

    def test_store_summary(self, iep4):
        from datetime import datetime
        ss = iep4.StoreSummary(
            store_id="s1",
            period_start=datetime(2026, 1, 1),
            period_end=datetime(2026, 1, 2),
            total_visitors=100,
            avg_dwell_seconds=45.0,
        )
        assert ss.busiest_zone is None

    def test_traffic_time_series_empty(self, iep4):
        ts = iep4.TrafficTimeSeries(store_id="s1", granularity="hour")
        assert ts.buckets == []


# ─── IEP5: Agent schemas ────────────────────────────────────────────────────

class TestIEP5Schemas:
    def test_agent_query(self, iep5):
        q = iep5.AgentQuery(store_id="s1", question="How busy was checkout?")
        assert q.context is None

    def test_agent_response(self, iep5):
        r = iep5.AgentResponse(answer="It was very busy.", confidence=0.85)
        assert r.sources == []
        assert r.charts == []

    def test_report_request(self, iep5):
        rr = iep5.ReportRequest(store_id="s1", report_type="daily_summary")
        assert rr.start is None

    def test_suggestion(self, iep5):
        from datetime import datetime
        sg = iep5.Suggestion(
            id="sug1",
            store_id="s1",
            category="layout",
            title="Move display",
            detail="Move electronics display closer to entrance",
            priority="high",
            created_at=datetime(2026, 4, 1),
        )
        assert sg.priority == "high"
