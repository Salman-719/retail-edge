"""Zone and Obstacle schemas."""
from __future__ import annotations
from datetime import datetime
from typing import Optional, List, Any

from pydantic import BaseModel, field_validator

from app.schemas.common import Point


class ZoneCreate(BaseModel):
    id: Optional[str] = None  # allow client to supply its own ID
    name: str
    type: str
    points: List[Point]

    @field_validator("type")
    @classmethod
    def validate_type(cls, v: str) -> str:
        allowed = {"entrance", "checkout", "aisle", "staff_only", "general"}
        if v not in allowed:
            raise ValueError(f"type must be one of {allowed}")
        return v


class ZoneUpdate(BaseModel):
    name: Optional[str] = None
    type: Optional[str] = None
    points: Optional[List[Point]] = None


class ZoneResponse(BaseModel):
    id: str
    store_id: str
    name: str
    type: str
    points: List[Any]
    created_at: datetime

    model_config = {"from_attributes": True}


class ObstacleCreate(BaseModel):
    id: Optional[str] = None
    name: Optional[str] = None
    points: List[Point]


class ObstacleUpdate(BaseModel):
    name: Optional[str] = None
    points: Optional[List[Point]] = None


class ObstacleResponse(BaseModel):
    id: str
    store_id: str
    name: Optional[str] = None
    points: List[Any]
    created_at: datetime

    model_config = {"from_attributes": True}
