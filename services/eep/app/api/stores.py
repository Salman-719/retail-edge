from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.models import db as models
from app.models.schemas import StoreCreate, StoreResponse

router = APIRouter()


@router.get("", response_model=list[StoreResponse])
async def list_stores(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(models.Store).order_by(models.Store.created_at))
    return result.scalars().all()


@router.post("", response_model=StoreResponse, status_code=201)
async def create_store(payload: StoreCreate, db: AsyncSession = Depends(get_db)):
    store = models.Store(name=payload.name)
    db.add(store)
    await db.flush()
    await db.refresh(store)
    return store


@router.get("/{store_id}", response_model=StoreResponse)
async def get_store(store_id: str, db: AsyncSession = Depends(get_db)):
    store = await db.get(models.Store, store_id)
    if not store:
        raise HTTPException(404, "Store not found")
    return store


@router.delete("/{store_id}", status_code=204)
async def delete_store(store_id: str, db: AsyncSession = Depends(get_db)):
    store = await db.get(models.Store, store_id)
    if not store:
        raise HTTPException(404, "Store not found")
    await db.delete(store)
