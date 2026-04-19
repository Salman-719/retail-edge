"""IEP4 — Analytics Aggregation.

Reads FrameRecord rows from the database and aggregates them into time-series analytics.
Stub endpoints — logic will be implemented in Milestone 3.
"""
from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import FastAPI, Query

from app.schemas import (
    AnalyticsQueryRequest,
    AggregateAck,
    StoreSummary,
    ZoneAnalytics,
    TrafficTimeSeries,
    Granularity,
    HealthResponse,
)

app = FastAPI(
    title="RetailVision IEP4 — Analytics",
    version="0.1.0",
    description="Aggregates tracking data into time-series analytics and reports.",
)


# ── Health ───────────────────────────────────────────────────────────────────

@app.get("/health", response_model=HealthResponse)
async def health():
    return HealthResponse()


# ── Ingestion ────────────────────────────────────────────────────────────────

@app.post("/analytics/aggregate", status_code=202, response_model=AggregateAck)
async def aggregate(request: AnalyticsQueryRequest):
    """Read FrameRecord rows from the DB and aggregate them.
    Stub — stores nothing until persistence is implemented."""
    # TODO: query DB for FrameRecord rows matching request.store_id / camera_id / time window
    # TODO: compute visitor counts, dwell times, zone occupancy and write results back to DB
    return AggregateAck()


# ── Queries ──────────────────────────────────────────────────────────────────

@app.get("/analytics/{store_id}/summary", response_model=StoreSummary)
async def store_summary(
    store_id: str,
    start: Optional[datetime] = Query(None),
    end: Optional[datetime] = Query(None),
    granularity: Granularity = Query("day"),
):
    """Return aggregated store summary for a time period.
    Stub — returns zeroed placeholder."""
    now = datetime.utcnow()
    return StoreSummary(
        store_id=store_id,
        period_start=start or (now - timedelta(days=1)),
        period_end=end or now,
        total_visitors=0,
        avg_dwell_seconds=0.0,
    )


@app.get("/analytics/{store_id}/zones", response_model=List[ZoneAnalytics])
async def zone_analytics(
    store_id: str,
    start: Optional[datetime] = Query(None),
    end: Optional[datetime] = Query(None),
):
    """Return per-zone analytics for a time period.
    Stub — returns empty list."""
    return []


@app.get("/analytics/{store_id}/traffic", response_model=TrafficTimeSeries)
async def traffic_time_series(
    store_id: str,
    start: Optional[datetime] = Query(None),
    end: Optional[datetime] = Query(None),
    granularity: Granularity = Query("hour"),
):
    """Return visitor traffic as a time-series.
    Stub — returns empty buckets."""
    return TrafficTimeSeries(
        store_id=store_id,
        granularity=granularity,
        buckets=[],
    )
