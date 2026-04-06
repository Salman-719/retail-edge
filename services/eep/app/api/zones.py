from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.models import db as models
from app.models.schemas import (
    ZoneCreate, ZoneUpdate, ZoneResponse,
    ObstacleCreate, ObstacleUpdate, ObstacleResponse,
)

router = APIRouter()


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
    zone = models.Zone(
        id=payload.id,
        store_id=store_id,
        name=payload.name,
        type=payload.type,
        points=[p.model_dump() for p in payload.points],
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
    if payload.name is not None:
        zone.name = payload.name
    if payload.type is not None:
        zone.type = payload.type
    if payload.points is not None:
        zone.points = [p.model_dump() for p in payload.points]
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
