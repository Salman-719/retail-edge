"""Store and FloorPlan schemas."""
from __future__ import annotations
from datetime import datetime
from typing import Optional

from pydantic import BaseModel

from app.schemas.common import Point


class StoreCreate(BaseModel):
    name: str


class StoreResponse(BaseModel):
    id: str
    name: str
    created_at: datetime

    model_config = {"from_attributes": True}


class ScaleConfig(BaseModel):
    origin_px: Optional[Point] = None
    scale_point1_px: Optional[Point] = None
    scale_point2_px: Optional[Point] = None
    real_world_distance_m: Optional[float] = None
    pixels_per_meter: Optional[float] = None


class FloorPlanResponse(BaseModel):
    id: str
    store_id: str
    s3_key: Optional[str] = None
    width_px: Optional[int] = None
    height_px: Optional[int] = None
    origin_x: Optional[float] = None
    origin_y: Optional[float] = None
    scale_point1_x: Optional[float] = None
    scale_point1_y: Optional[float] = None
    scale_point2_x: Optional[float] = None
    scale_point2_y: Optional[float] = None
    real_world_distance_m: Optional[float] = None
    pixels_per_meter: Optional[float] = None

    model_config = {"from_attributes": True}
