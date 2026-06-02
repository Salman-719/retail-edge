from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.middleware.store_auth import StoreContext, get_store_context
from app.models.physical_camera import PhysicalCamera

router = APIRouter(tags=["vision"])


def _require_internal(token: str | None) -> None:
    if settings.VISION_INTERNAL_TOKEN and token != settings.VISION_INTERNAL_TOKEN:
        raise HTTPException(status_code=403, detail={"error": "Forbidden", "code": "FORBIDDEN"})


def _row_dict(row) -> dict[str, Any]:
    out = dict(row._mapping)
    for key, value in list(out.items()):
        if isinstance(value, uuid.UUID):
            out[key] = str(value)
        elif isinstance(value, datetime):
            out[key] = value.isoformat()
    return out


async def _topology(db: AsyncSession, store_id: uuid.UUID) -> dict[str, Any]:
    version = (
        await db.execute(
            text(
                """
                SELECT id, label
                FROM store_config_versions
                WHERE store_id = :store_id AND status = 'active'
                ORDER BY active_from DESC NULLS LAST, created_at DESC
                LIMIT 1
                """
            ),
            {"store_id": store_id},
        )
    ).first()
    if version is None:
        raise HTTPException(status_code=404, detail={"error": "No active version", "code": "NO_ACTIVE_VERSION"})

    section_rows = (
        await db.execute(
            text(
                """
                SELECT id AS section_id, name, type, display_order
                FROM sections
                WHERE store_id = :store_id AND status = 'active'
                ORDER BY display_order
                """
            ),
            {"store_id": store_id},
        )
    ).all()
    sections = [_row_dict(row) | {"cameras": []} for row in section_rows]
    by_section = {section["section_id"]: section for section in sections}

    camera_rows = (
        await db.execute(
            text(
                """
                SELECT cc.id AS camera_config_id,
                       cc.section_id,
                       pc.id AS camera_id,
                       pc.name,
                       pc.cloud_stream_url AS stream_url,
                       pc.health_status,
                       pc.last_seen_at,
                       pc.last_error,
                       cc.video_width,
                       cc.video_height
                FROM camera_configs cc
                JOIN physical_cameras pc ON pc.id = cc.physical_camera_id
                WHERE cc.version_id = :version_id
                  AND pc.store_id = :store_id
                  AND pc.is_active = TRUE
                  AND cc.status != 'disabled'
                ORDER BY pc.created_at
                """
            ),
            {"store_id": store_id, "version_id": version.id},
        )
    ).all()
    for row in camera_rows:
        item = _row_dict(row)
        section = by_section.get(item["section_id"])
        if section is not None:
            section["cameras"].append(item)

    return {
        "store_id": str(store_id),
        "version_id": str(version.id),
        "version_label": version.label,
        "sections": sections,
    }


@router.get("/store/{slug}/vision/topology")
async def get_store_vision_topology(
    ctx: StoreContext = Depends(get_store_context),
    db: AsyncSession = Depends(get_db),
):
    return await _topology(db, ctx.store_id)


@router.get("/internal/vision/topology")
async def get_internal_vision_topology(
    store_id: uuid.UUID = Query(...),
    x_vision_internal_token: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    _require_internal(x_vision_internal_token)
    return await _topology(db, store_id)


@router.get("/store/{slug}/vision/identities")
async def list_global_identities(
    limit: int = Query(100, ge=1, le=1000),
    ctx: StoreContext = Depends(get_store_context),
    db: AsyncSession = Depends(get_db),
):
    rows = (
        await db.execute(
            text(
                """
                SELECT global_id, first_seen_ts, last_seen_ts, state,
                       last_floor_x, last_floor_y
                FROM global_identities
                WHERE store_id = :store_id
                ORDER BY last_seen_ts DESC
                LIMIT :limit
                """
            ),
            {"store_id": ctx.store_id, "limit": limit},
        )
    ).all()
    return {"identities": [_row_dict(row) for row in rows]}


@router.get("/store/{slug}/vision/observations/latest")
async def latest_global_observations(
    limit: int = Query(200, ge=1, le=1000),
    ctx: StoreContext = Depends(get_store_context),
    db: AsyncSession = Depends(get_db),
):
    rows = (
        await db.execute(
            text(
                """
                SELECT global_id, batch_number, timestamp_ms, floor_x, floor_y, zone_id,
                       source_camera, source_local_id, selection_score
                FROM global_tracking_history
                WHERE store_id = :store_id
                ORDER BY timestamp_ms DESC
                LIMIT :limit
                """
            ),
            {"store_id": ctx.store_id, "limit": limit},
        )
    ).all()
    return {"observations": [_row_dict(row) for row in rows]}


@router.get("/store/{slug}/vision/tracks/latest")
async def latest_local_tracks(
    limit: int = Query(200, ge=1, le=1000),
    ctx: StoreContext = Depends(get_store_context),
    db: AsyncSession = Depends(get_db),
):
    rows = (
        await db.execute(
            text(
                """
                SELECT DISTINCT ON (th.local_id)
                       th.local_id, glm.global_id, th.camera_id, th.timestamp_ms,
                       th.floor_x, th.floor_y, th.zone_id, th.bbox_confidence,
                       th.bbox_x1, th.bbox_y1, th.bbox_x2, th.bbox_y2
                FROM tracking_history th
                LEFT JOIN global_local_mapping glm ON glm.local_id = th.local_id AND glm.is_active = TRUE
                JOIN camera_configs cc ON cc.physical_camera_id::text = th.camera_id
                WHERE cc.version_id IN (
                    SELECT id FROM store_config_versions
                    WHERE store_id = :store_id AND status = 'active'
                )
                ORDER BY th.local_id, th.timestamp_ms DESC
                LIMIT :limit
                """
            ),
            {"store_id": ctx.store_id, "limit": limit},
        )
    ).all()
    return {"tracks": [_row_dict(row) for row in rows]}


@router.get("/store/{slug}/vision/camera-health")
async def camera_health(
    ctx: StoreContext = Depends(get_store_context),
    db: AsyncSession = Depends(get_db),
):
    rows = (
        await db.execute(
            text(
                """
                SELECT id AS camera_id, name, health_status, last_seen_at, last_error
                FROM physical_cameras
                WHERE store_id = :store_id AND is_active = TRUE
                ORDER BY created_at
                """
            ),
            {"store_id": ctx.store_id},
        )
    ).all()
    return {"cameras": [_row_dict(row) for row in rows]}


@router.post("/internal/vision/camera-health")
async def update_camera_health(
    payload: dict[str, Any],
    x_vision_internal_token: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    _require_internal(x_vision_internal_token)
    camera_id = payload.get("camera_id")
    if not camera_id:
        raise HTTPException(status_code=422, detail={"error": "camera_id is required", "code": "BAD_PAYLOAD"})
    values = {
        "health_status": payload.get("status", "online"),
        "last_error": payload.get("last_error"),
    }
    last_seen_at = payload.get("last_seen_at")
    if last_seen_at:
        values["last_seen_at"] = datetime.fromisoformat(last_seen_at.replace("Z", "+00:00"))
    await db.execute(update(PhysicalCamera).where(PhysicalCamera.id == uuid.UUID(str(camera_id))).values(**values))
    await db.commit()
    return {"status": "ok"}


# ── Edge connectivity heartbeat ────────────────────────────────────────────────
# Store-level "is the Jetson reaching the cloud" signal — independent of cameras
# or any published config. IEP1 posts this on a timer; the GUI reads edge-status.
# Stored in Redis with a TTL so "connected" means "pinged within the TTL window".

_EDGE_HB_TTL = 60  # seconds; a missed window marks the edge disconnected


def _redis():
    import redis.asyncio as aioredis
    return aioredis.from_url(settings.REDIS_URL)


@router.post("/internal/vision/edge-heartbeat")
async def edge_heartbeat(
    payload: dict[str, Any],
    x_vision_internal_token: str | None = Header(default=None),
):
    _require_internal(x_vision_internal_token)
    store_id = payload.get("store_id")
    if not store_id:
        raise HTTPException(status_code=422, detail={"error": "store_id is required", "code": "BAD_PAYLOAD"})
    import json
    r = _redis()
    try:
        await r.set(
            f"edge:hb:{store_id}",
            json.dumps({
                "last_seen": datetime.utcnow().isoformat() + "Z",
                "hostname": payload.get("hostname", ""),
            }),
            ex=_EDGE_HB_TTL,
        )
    finally:
        await r.aclose()
    return {"status": "ok"}


@router.get("/store/{slug}/vision/edge-status")
async def edge_status(
    ctx: StoreContext = Depends(get_store_context),
):
    import json
    r = _redis()
    try:
        raw = await r.get(f"edge:hb:{ctx.store_id}")
    finally:
        await r.aclose()
    if not raw:
        return {"connected": False, "last_seen": None, "hostname": None}
    data = json.loads(raw)
    return {"connected": True, "last_seen": data.get("last_seen"), "hostname": data.get("hostname")}
