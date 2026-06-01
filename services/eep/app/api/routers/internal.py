"""Internal endpoints — called by edge IEP2 workers, not the frontend.

Auth: X-Internal-Token header must match VISION_INTERNAL_TOKEN.
These routes are NOT prefixed with /api to distinguish them from frontend routes.
"""
from __future__ import annotations

import json
import uuid
from typing import Optional

import redis.asyncio as aioredis
import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Header
from pydantic import BaseModel

from app.core.config import settings
from app.core.database import AsyncSessionLocal

router = APIRouter(prefix="/internal", tags=["internal"])


# ── Auth ──────────────────────────────────────────────────────────────────────

def _require_internal(x_internal_token: str = Header(...)) -> None:
    if not settings.VISION_INTERNAL_TOKEN or x_internal_token != settings.VISION_INTERNAL_TOKEN:
        raise HTTPException(403, "Invalid internal token")


# ── Payload schemas ───────────────────────────────────────────────────────────

class PositionRow(BaseModel):
    local_id: str
    timestamp_ms: int
    floor_x: float
    floor_y: float
    zone_id: Optional[str] = None
    bbox_confidence: float
    bbox_area: float
    bbox_x1: float
    bbox_y1: float
    bbox_x2: float
    bbox_y2: float


class EmbeddingRow(BaseModel):
    local_id: str
    captured_ts: int
    embedding: list[float]
    yolo_confidence: float
    is_init: bool = False


class CentroidRow(BaseModel):
    local_id: str
    centroid: list[float]
    batch_number: int


class TrackingBatch(BaseModel):
    camera_id: str
    batch_number: int
    window_start_ms: int
    window_end_ms: int
    positions: list[PositionRow] = []
    embeddings: list[EmbeddingRow] = []
    centroids: list[CentroidRow] = []


# ── Endpoint ──────────────────────────────────────────────────────────────────

@router.post("/stores/{store_id}/tracking-batch", status_code=202,
             dependencies=[Depends(_require_internal)])
async def ingest_tracking_batch(store_id: str, batch: TrackingBatch):
    """Receive a tracking batch from an edge IEP2 worker.

    Writes positions, embeddings and centroids to the DB, then publishes a
    batch_complete event to the per-store Redis stream so IEP3 wakes up.
    """
    async with AsyncSessionLocal() as session:
        if batch.positions:
            await session.execute(
                sa.text(
                    "INSERT INTO tracking_history "
                    "(id, store_id, camera_id, local_id, timestamp_ms, "
                    " floor_x, floor_y, zone_id, "
                    " bbox_confidence, bbox_area, bbox_x1, bbox_y1, bbox_x2, bbox_y2) "
                    "VALUES (:id, :store_id, :camera_id, :local_id, :timestamp_ms, "
                    " :floor_x, :floor_y, :zone_id, "
                    " :bbox_confidence, :bbox_area, :bbox_x1, :bbox_y1, :bbox_x2, :bbox_y2) "
                    "ON CONFLICT DO NOTHING"
                ),
                [
                    {
                        "id": uuid.uuid4().hex,
                        "store_id": store_id,
                        "camera_id": batch.camera_id,
                        "local_id": p.local_id,
                        "timestamp_ms": p.timestamp_ms,
                        "floor_x": p.floor_x,
                        "floor_y": p.floor_y,
                        "zone_id": p.zone_id,
                        "bbox_confidence": p.bbox_confidence,
                        "bbox_area": p.bbox_area,
                        "bbox_x1": p.bbox_x1,
                        "bbox_y1": p.bbox_y1,
                        "bbox_x2": p.bbox_x2,
                        "bbox_y2": p.bbox_y2,
                    }
                    for p in batch.positions
                ],
            )

        if batch.embeddings:
            await session.execute(
                sa.text(
                    "INSERT INTO local_embeddings "
                    "(id, store_id, camera_id, local_id, captured_ts, "
                    " embedding, yolo_confidence, is_init) "
                    "VALUES (:id, :store_id, :camera_id, :local_id, :captured_ts, "
                    " CAST(:embedding AS jsonb), :yolo_confidence, :is_init) "
                    "ON CONFLICT DO NOTHING"
                ),
                [
                    {
                        "id": uuid.uuid4().hex,
                        "store_id": store_id,
                        "camera_id": batch.camera_id,
                        "local_id": e.local_id,
                        "captured_ts": e.captured_ts,
                        "embedding": json.dumps(e.embedding),
                        "yolo_confidence": e.yolo_confidence,
                        "is_init": e.is_init,
                    }
                    for e in batch.embeddings
                ],
            )

        if batch.centroids:
            for c in batch.centroids:
                await session.execute(
                    sa.text(
                        "INSERT INTO local_centroids "
                        "(id, store_id, camera_id, local_id, centroid, batch_number) "
                        "VALUES (:id, :store_id, :camera_id, :local_id, "
                        " CAST(:centroid AS jsonb), :batch_number) "
                        "ON CONFLICT (camera_id, local_id) DO UPDATE "
                        "SET centroid = EXCLUDED.centroid, batch_number = EXCLUDED.batch_number"
                    ),
                    {
                        "id": uuid.uuid4().hex,
                        "store_id": store_id,
                        "camera_id": batch.camera_id,
                        "local_id": c.local_id,
                        "centroid": json.dumps(c.centroid),
                        "batch_number": c.batch_number,
                    },
                )

        await session.commit()

    # Publish batch_complete to per-store Redis stream so IEP3 wakes up
    try:
        r = aioredis.from_url(settings.REDIS_URL)
        await r.xadd(
            f"stream:store:{store_id}:batch_complete",
            {
                "store_id": store_id,
                "camera_id": batch.camera_id,
                "batch_number": str(batch.batch_number),
                "window_start_ms": str(batch.window_start_ms),
                "window_end_ms": str(batch.window_end_ms),
            },
        )
        await r.aclose()
    except Exception:
        pass  # Redis down: IEP3 will catch up from DB on reconnect

    return {"accepted": True, "batch_number": batch.batch_number}
