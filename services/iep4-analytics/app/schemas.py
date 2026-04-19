"""IEP4 — Analytics Aggregation Service: I/O contract.

All request bodies, query parameters, and response payloads are declared here so
every endpoint has an explicit, typed, documented contract.

Endpoint catalogue
------------------

POST /analytics/ingest
    Input :  TrackingSnapshot                 (sent by IEP2 after tracking)
    Output:  IngestAck                        (202)

GET  /analytics/{store_id}/summary
    Query :  start:datetime|None, end:datetime|None, granularity:Granularity="day"
    Output:  StoreSummary                     (200)

GET  /analytics/{store_id}/zones
    Query :  start:datetime|None, end:datetime|None
    Output:  List[ZoneAnalytics]              (200)

GET  /analytics/{store_id}/traffic
    Query :  start:datetime|None, end:datetime|None, granularity:Granularity="hour"
    Output:  TrafficTimeSeries                (200)

GET  /health
    Output:  HealthResponse                   (200)
"""
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field


# ── Health ────────────────────────────────────────────────────────────────────

class HealthResponse(BaseModel):
    service: str = "iep4-analytics"
    status: str = "ok"


# ── Shared primitives ─────────────────────────────────────────────────────────

Granularity = Literal["hour", "day", "week"]


class ZoneOccupancy(BaseModel):
    """Dwell statistics for a single zone during a tracking run."""
    seconds: float = Field(..., ge=0)
    percent: float = Field(..., ge=0, le=100)


# ── Ingestion ─────────────────────────────────────────────────────────────────

class TrackingSnapshot(BaseModel):
    """Sent by IEP2 after a tracking job completes — raw data for aggregation."""
    store_id: str
    camera_id: str
    zone_occupancy: Dict[str, ZoneOccupancy] = Field(default_factory=dict)
    trajectory: List[Dict[str, Any]] = Field(default_factory=list)
    total_frames: int = Field(..., ge=0)
    fps: float = Field(..., ge=0)
    recorded_at: Optional[datetime] = None


class IngestAck(BaseModel):
    accepted: bool = True


# ── Store summary ─────────────────────────────────────────────────────────────

class ZoneSummary(BaseModel):
    """Aggregated per-zone stats rolled up across a time period."""
    total_dwell_seconds: float = Field(..., ge=0)
    avg_dwell_seconds: float = Field(..., ge=0)
    visit_count: int = Field(..., ge=0)


class StoreSummary(BaseModel):
    store_id: str
    period_start: datetime
    period_end: datetime
    total_visitors: int = Field(..., ge=0)
    avg_dwell_seconds: float = Field(..., ge=0)
    busiest_zone: Optional[str] = None
    zones: Dict[str, ZoneSummary] = Field(default_factory=dict)


# ── Zone analytics ────────────────────────────────────────────────────────────

class ZoneAnalytics(BaseModel):
    zone_name: str
    total_dwell_seconds: float = Field(..., ge=0)
    avg_dwell_seconds: float = Field(..., ge=0)
    peak_occupancy: int = Field(..., ge=0)
    visit_count: int = Field(..., ge=0)


# ── Traffic time-series ───────────────────────────────────────────────────────

class TrafficBucket(BaseModel):
    timestamp: datetime
    visitor_count: int = Field(..., ge=0)


class TrafficTimeSeries(BaseModel):
    store_id: str
    granularity: Granularity
    buckets: List[TrafficBucket] = Field(default_factory=list)
