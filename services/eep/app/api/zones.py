from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from shapely.geometry import Polygon as ShapelyPolygon

from app.core.database import get_db
from app.models import db as models
from app.models.schemas import (
    ZoneCreate, ZoneUpdate, ZoneResponse,
    ObstacleCreate, ObstacleUpdate, ObstacleResponse,
)

router = APIRouter()


def _check_zone_overlap(new_points: list[dict], existing_zones: list, exclude_id: str | None = None):
    """Raise 409 if new zone polygon overlaps any existing zone."""
    if len(new_points) < 3:
        return
    new_poly = ShapelyPolygon([(p["x"], p["y"]) for p in new_points])
    if not new_poly.is_valid:
        return
    for zone in existing_zones:
        if exclude_id and zone.id == exclude_id:
            continue
        pts = zone.points
        if len(pts) < 3:
            continue
        existing_poly = ShapelyPolygon([(p["x"], p["y"]) for p in pts])
        if not existing_poly.is_valid:
            continue
        intersection = new_poly.intersection(existing_poly)
        # Allow touching edges (area=0) but not real overlap
        if intersection.area > 0:
            raise HTTPException(
                409,
                f"Zone overlaps with existing zone '{zone.name}'"
            )


# ─── Zones ────────────────────────────────────────────────────────────────────

@router.get("/{store_id}/zones", response_model=list[ZoneResponse])
async def list_zones(store_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(models.Zone).where(models.Zone.store_id == store_id)
    )
    return result.scalars().all()


@router.post("/{store_id}/zones", response_model=ZoneResponse, status_code=201)
async def create_zone(store_id: str, payload: ZoneCreate, db: AsyncSession = Depends(get_db)):
    store = await db.get(models.Store, store_id)
    if not store:
        raise HTTPException(404, "Store not found")

    # Overlap check
    result = await db.execute(select(models.Zone).where(models.Zone.store_id == store_id))
    existing_zones = result.scalars().all()
    points_dicts = [p.model_dump() for p in payload.points]
    _check_zone_overlap(points_dicts, existing_zones, exclude_id=payload.id)

    if payload.id:
        existing = await db.get(models.Zone, payload.id)
        if existing and existing.store_id == store_id:
            existing.name = payload.name
            existing.type = payload.type
            existing.points = points_dicts
            await db.flush()
            await db.refresh(existing)
            return existing
    zone = models.Zone(
        id=payload.id,
        store_id=store_id,
        name=payload.name,
        type=payload.type,
        points=points_dicts,
    )
    db.add(zone)
    await db.flush()
    await db.refresh(zone)
    return zone


@router.put("/{store_id}/zones/{zone_id}", response_model=ZoneResponse)
async def update_zone(store_id: str, zone_id: str, payload: ZoneUpdate, db: AsyncSession = Depends(get_db)):
    zone = await db.get(models.Zone, zone_id)
    if not zone or zone.store_id != store_id:
        raise HTTPException(404, "Zone not found")
    if payload.points is not None:
        result = await db.execute(select(models.Zone).where(models.Zone.store_id == store_id))
        existing_zones = result.scalars().all()
        points_dicts = [p.model_dump() for p in payload.points]
        _check_zone_overlap(points_dicts, existing_zones, exclude_id=zone_id)
        zone.points = points_dicts
    if payload.name is not None:
        zone.name = payload.name
    if payload.type is not None:
        zone.type = payload.type
    await db.flush()
    await db.refresh(zone)
    return zone


@router.delete("/{store_id}/zones/{zone_id}", status_code=204)
async def delete_zone(store_id: str, zone_id: str, db: AsyncSession = Depends(get_db)):
    zone = await db.get(models.Zone, zone_id)
    if not zone or zone.store_id != store_id:
        raise HTTPException(404, "Zone not found")
    await db.delete(zone)


# ─── Obstacles ────────────────────────────────────────────────────────────────

@router.get("/{store_id}/obstacles", response_model=list[ObstacleResponse])
async def list_obstacles(store_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(models.Obstacle).where(models.Obstacle.store_id == store_id)
    )
    return result.scalars().all()


@router.post("/{store_id}/obstacles", response_model=ObstacleResponse, status_code=201)
async def create_obstacle(store_id: str, payload: ObstacleCreate, db: AsyncSession = Depends(get_db)):
    store = await db.get(models.Store, store_id)
    if not store:
        raise HTTPException(404, "Store not found")
    if payload.id:
        existing = await db.get(models.Obstacle, payload.id)
        if existing and existing.store_id == store_id:
            existing.name = payload.name
            existing.points = [p.model_dump() for p in payload.points]
            await db.flush()
            await db.refresh(existing)
            return existing
    obs = models.Obstacle(
        id=payload.id,
        store_id=store_id,
        name=payload.name,
        points=[p.model_dump() for p in payload.points],
    )
    db.add(obs)
    await db.flush()
    await db.refresh(obs)
    return obs


@router.put("/{store_id}/obstacles/{obs_id}", response_model=ObstacleResponse)
async def update_obstacle(store_id: str, obs_id: str, payload: ObstacleUpdate, db: AsyncSession = Depends(get_db)):
    obs = await db.get(models.Obstacle, obs_id)
    if not obs or obs.store_id != store_id:
        raise HTTPException(404, "Obstacle not found")
    if payload.name is not None:
        obs.name = payload.name
    if payload.points is not None:
        obs.points = [p.model_dump() for p in payload.points]
    await db.flush()
    await db.refresh(obs)
    return obs


@router.delete("/{store_id}/obstacles/{obs_id}", status_code=204)
async def delete_obstacle(store_id: str, obs_id: str, db: AsyncSession = Depends(get_db)):
    obs = await db.get(models.Obstacle, obs_id)
    if not obs or obs.store_id != store_id:
        raise HTTPException(404, "Obstacle not found")
    await db.delete(obs)
