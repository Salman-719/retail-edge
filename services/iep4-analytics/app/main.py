"""IEP4 — Analytics Aggregation.

Aggregates tracking data into time-series analytics and reports.
Stub endpoints — logic will be implemented in Milestone 3.
"""
from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import FastAPI, Query

from app.schemas import (
    TrackingSnapshot,
    StoreSummary,
    ZoneAnalytics,
    TrafficTimeSeries,
)

app = FastAPI(
    title="RetailVision IEP4 — Analytics",
    version="0.1.0",
    description="Aggregates tracking data into time-series analytics and reports.",
)


# ── Health ───────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"service": "iep4-analytics", "status": "ok"}


# ── Ingestion ────────────────────────────────────────────────────────────────

@app.post("/analytics/ingest", status_code=202)
async def ingest(snapshot: TrackingSnapshot):
    """Receive a tracking snapshot and aggregate it.
    Stub — stores nothing until persistence is implemented."""
    # TODO: persist snapshot into time-series storage
    return {"accepted": True}


# ── Queries ──────────────────────────────────────────────────────────────────

@app.get("/analytics/{store_id}/summary", response_model=StoreSummary)
async def store_summary(
    store_id: str,
    start: Optional[datetime] = Query(None),
    end: Optional[datetime] = Query(None),
    granularity: str = Query("day"),
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
    granularity: str = Query("hour"),
):
    """Return visitor traffic as a time-series.
    Stub — returns empty buckets."""
    return TrafficTimeSeries(
        store_id=store_id,
        granularity=granularity,
        buckets=[],
    )
