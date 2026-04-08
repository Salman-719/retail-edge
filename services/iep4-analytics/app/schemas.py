"""IEP4 — Analytics Aggregation schemas.

Defines the input/output contract for the analytics service.

Endpoints:
  POST /analytics/ingest
    Input:  TrackingSnapshot (sent by IEP2 after each tracking job)
    Output: 202

  GET  /analytics/{store_id}/summary
    Input:  query params: start, end, granularity
    Output: StoreSummary

  GET  /analytics/{store_id}/zones
    Input:  query params: start, end
    Output: List[ZoneAnalytics]

  GET  /analytics/{store_id}/traffic
    Input:  query params: start, end, granularity
    Output: TrafficTimeSeries
"""
from datetime import datetime
from typing import List, Optional, Dict
from pydantic import BaseModel


# ── Ingestion ────────────────────────────────────────────────────────────────

class TrackingSnapshot(BaseModel):
    """Sent by IEP2 after a tracking job completes — raw data for aggregation."""
    store_id: str
    camera_id: str
    zone_occupancy: Dict[str, Dict]      # {zone_name: {seconds, percent}}
    trajectory: List[Dict]
    total_frames: int
    fps: float
    recorded_at: Optional[datetime] = None


# ── Store summary ────────────────────────────────────────────────────────────

class StoreSummary(BaseModel):
    store_id: str
    period_start: datetime
    period_end: datetime
    total_visitors: int
    avg_dwell_seconds: float
    busiest_zone: Optional[str] = None
    zones: Dict[str, Dict] = {}          # zone_name → aggregated stats


# ── Zone analytics ───────────────────────────────────────────────────────────

class ZoneAnalytics(BaseModel):
    zone_name: str
    total_dwell_seconds: float
    avg_dwell_seconds: float
    peak_occupancy: int
    visit_count: int


# ── Traffic time-series ──────────────────────────────────────────────────────

class TrafficBucket(BaseModel):
    timestamp: datetime
    visitor_count: int

class TrafficTimeSeries(BaseModel):
    store_id: str
    granularity: str                     # "hour" | "day" | "week"
    buckets: List[TrafficBucket] = []
