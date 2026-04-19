"""IEP4 — Analytics Aggregation Service: I/O contract.

All request bodies, query parameters, and response payloads are declared here so
every endpoint has an explicit, typed, documented contract.

Endpoint catalogue
------------------

POST /analytics/aggregate
    Input :  AnalyticsQueryRequest            (store/camera + optional time window)
    IEP4 reads FrameRecord rows from the DB itself — no tracking data in body.
    Output:  TBD                              (202)

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
from typing import Dict, List, Literal, Optional
from pydantic import BaseModel, Field


# ── Health ────────────────────────────────────────────────────────────────────

class HealthResponse(BaseModel):
    service: str = "iep4-analytics"
    status: str = "ok"


# ── Shared primitives ─────────────────────────────────────────────────────────

Granularity = Literal["hour", "day", "week"]


# ── Aggregation trigger (reads from DB) ──────────────────────────────────────

class AnalyticsQueryRequest(BaseModel):
    """Trigger IEP4 to read FrameRecord rows from the DB and aggregate them.
    IEP4 queries the DB itself — no tracking data is passed in the request body."""
    store_id: str
    camera_id: Optional[str] = Field(None, description="None = aggregate all cameras for the store")
    start: Optional[datetime] = None
    end: Optional[datetime] = None
    granularity: Granularity = "hour"


class AggregateAck(BaseModel):
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
