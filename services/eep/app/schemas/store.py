"""Store and FloorPlan schemas."""
from __future__ import annotations
from datetime import datetime
from typing import Optional

from pydantic import BaseModel

from app.schemas.common import Point


class StoreCreate(BaseModel):
    name: str
    onboarding_method: str = "standard"


class StoreResponse(BaseModel):
    id: str
    name: str
    onboarding_method: str = "standard"
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
    # Method 2: virtual canvas bounds in world meters
    world_x_min: Optional[float] = None
    world_x_max: Optional[float] = None
    world_y_min: Optional[float] = None
    world_y_max: Optional[float] = None

    model_config = {"from_attributes": True}


class WorldBoundsConfig(BaseModel):
    world_x_min: float
    world_x_max: float
    world_y_min: float
    world_y_max: float
