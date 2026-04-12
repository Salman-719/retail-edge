"""Unit tests for IEP service Pydantic schemas."""
import sys
import os

# Allow importing from IEP services
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../services/iep1-ingestion"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../services/iep2-vision"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../services/iep3-alerts"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../services/iep4-analytics"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../services/iep5-agent"))

import pytest
from pydantic import ValidationError


# ─── IEP1: Ingestion schemas ────────────────────────────────────────────────

class TestIEP1Schemas:
    def test_video_upload_response(self):
        from app.schemas import VideoUploadResponse
        r = VideoUploadResponse(
            camera_id="cam1",
            video_s3_key="stores/s1/cameras/cam1/video.mp4",
            video_fps=30.0,
            video_duration=120.5,
            video_width=1920,
            video_height=1080,
        )
        assert r.camera_id == "cam1"
        assert r.video_fps == 30.0

    def test_video_upload_response_missing_field(self):
        from app.schemas import VideoUploadResponse
        with pytest.raises(ValidationError):
            VideoUploadResponse(camera_id="cam1")  # missing required fields


# ─── IEP2: Vision schemas ───────────────────────────────────────────────────

class TestIEP2Schemas:
    def test_tracking_start_request(self):
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../services/iep2-vision"))
        # Re-import from iep2 context
        import importlib
        import app.schemas as s2
        importlib.reload(s2)

        req = s2.TrackingStartRequest(
            video_s3_key="stores/s1/cameras/c1/video.mp4",
            homography_matrix=[[1, 0, 0], [0, 1, 0], [0, 0, 1]],
            zones=[{"name": "A", "points": [{"x": 0, "y": 0}]}],
            store_id="store1",
        )
        assert req.model_size == "yolov8n"  # default
        assert req.pixels_per_meter == 100.0  # default

    def test_tracking_progress_response(self):
        import importlib
        import app.schemas as s2
        importlib.reload(s2)

        r = s2.TrackingProgressResponse(
            status="running",
            progress=50,
            total_frames=1000,
        )
        assert r.zone_occupancy == {}
        assert r.error is None

    def test_zone_occupancy(self):
        import importlib
        import app.schemas as s2
        importlib.reload(s2)

        zo = s2.ZoneOccupancy(seconds=45.2, percent=23.1)
        assert zo.seconds == 45.2

    def test_trajectory_point(self):
        import importlib
        import app.schemas as s2
        importlib.reload(s2)

        tp = s2.TrajectoryPoint(frameIdx=100, x=3.5, y=7.2, trackId=5)
        assert tp.frameIdx == 100

    def test_trajectory_response_default_empty(self):
        import importlib
        import app.schemas as s2
        importlib.reload(s2)

        r = s2.TrajectoryResponse()
        assert r.trajectory == []


# ─── IEP3: Alerts schemas ───────────────────────────────────────────────────

class TestIEP3Schemas:
    def _reload(self):
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../services/iep3-alerts"))
        import importlib
        import app.schemas as s3
        importlib.reload(s3)
        return s3

    def test_alert_rule_create(self):
        s3 = self._reload()
        rule = s3.AlertRuleCreate(
            store_id="store1",
            name="Queue too long",
            type="zone_crowding",
            zone_name="Checkout",
            threshold=10,
        )
        assert rule.enabled is True  # default

    def test_tracking_event(self):
        s3 = self._reload()
        evt = s3.TrackingEvent(
            store_id="store1",
            camera_id="cam1",
            zone_occupancy={"Checkout": {"seconds": 30, "percent": 50}},
            trajectory=[],
            timestamp=1234567890.0,
        )
        assert evt.store_id == "store1"


# ─── IEP4: Analytics schemas ────────────────────────────────────────────────

class TestIEP4Schemas:
    def _reload(self):
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../services/iep4-analytics"))
        import importlib
        import app.schemas as s4
        importlib.reload(s4)
        return s4

    def test_tracking_snapshot(self):
        s4 = self._reload()
        snap = s4.TrackingSnapshot(
            store_id="store1",
            camera_id="cam1",
            zone_occupancy={"A": {"seconds": 10, "percent": 50}},
            trajectory=[],
            total_frames=100,
            fps=30.0,
        )
        assert snap.recorded_at is None  # optional

    def test_store_summary(self):
        from datetime import datetime
        s4 = self._reload()
        ss = s4.StoreSummary(
            store_id="s1",
            period_start=datetime(2026, 1, 1),
            period_end=datetime(2026, 1, 2),
            total_visitors=100,
            avg_dwell_seconds=45.0,
        )
        assert ss.busiest_zone is None

    def test_traffic_time_series_empty(self):
        s4 = self._reload()
        ts = s4.TrafficTimeSeries(store_id="s1", granularity="hour")
        assert ts.buckets == []


# ─── IEP5: Agent schemas ────────────────────────────────────────────────────

class TestIEP5Schemas:
    def _reload(self):
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../services/iep5-agent"))
        import importlib
        import app.schemas as s5
        importlib.reload(s5)
        return s5

    def test_agent_query(self):
        s5 = self._reload()
        q = s5.AgentQuery(store_id="s1", question="How busy was checkout?")
        assert q.context is None

    def test_agent_response(self):
        s5 = self._reload()
        r = s5.AgentResponse(answer="It was very busy.", confidence=0.85)
        assert r.sources == []
        assert r.charts == []

    def test_report_request(self):
        s5 = self._reload()
        rr = s5.ReportRequest(store_id="s1", report_type="daily_summary")
        assert rr.start is None

    def test_suggestion(self):
        from datetime import datetime
        s5 = self._reload()
        sg = s5.Suggestion(
            id="sug1",
            store_id="s1",
            category="layout",
            title="Move display",
            detail="Move electronics display closer to entrance",
            priority="high",
            created_at=datetime(2026, 4, 1),
        )
        assert sg.priority == "high"
