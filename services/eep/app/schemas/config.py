import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel


class SectionResponse(BaseModel):
    id: uuid.UUID
    name: str
    type: str
    display_order: int
    is_default: bool
    status: str

    model_config = {"from_attributes": True}


class FloorPlanResponse(BaseModel):
    id: uuid.UUID
    version_id: uuid.UUID
    section_id: uuid.UUID
    onboarding_method: str
    display_url: str | None = None
    width_px: int | None = None
    height_px: int | None = None
    origin_x: float | None = None
    origin_y: float | None = None
    pixels_per_meter: float | None = None
    world_x_min: float | None = None
    world_x_max: float | None = None
    world_y_min: float | None = None
    world_y_max: float | None = None
    image_uploaded: bool
    scale_defined: bool

    model_config = {"from_attributes": True}


class ZoneResponse(BaseModel):
    id: uuid.UUID
    version_id: uuid.UUID
    section_id: uuid.UUID
    name: str
    type: str
    points: list[list[float]]
    queue_threshold_people: int | None = None
    queue_threshold_minutes: int | None = None
    staff_absence_minutes: int | None = None

    model_config = {"from_attributes": True}


class ObstacleResponse(BaseModel):
    id: uuid.UUID
    version_id: uuid.UUID
    section_id: uuid.UUID
    name: str | None = None
    points: list[list[float]]

    model_config = {"from_attributes": True}


class PhysicalCameraResponse(BaseModel):
    id: uuid.UUID
    store_id: uuid.UUID
    name: str
    brand: str | None = None
    model: str | None = None
    mounting: str | None = None
    health_status: str
    is_active: bool
    last_seen_at: datetime | None = None

    model_config = {"from_attributes": True}


class CameraConfigSummary(BaseModel):
    id: uuid.UUID
    physical_camera_id: uuid.UUID
    physical_camera_name: str
    section_id: uuid.UUID
    position_x: float
    position_y: float
    height_meters: float | None = None
    fov_deg: float | None = None
    status: str
    frame_url: str | None = None

    model_config = {"from_attributes": True}


class SectionWithConfig(BaseModel):
    id: uuid.UUID
    name: str
    type: str
    display_order: int
    is_default: bool
    floor_plan: FloorPlanResponse | None = None
    zones: list[ZoneResponse] = []
    obstacles: list[ObstacleResponse] = []
    camera_configs: list[CameraConfigSummary] = []

    model_config = {"from_attributes": True}


class VersionListItem(BaseModel):
    id: uuid.UUID
    label: str | None = None
    status: str
    active_from: datetime | None = None
    active_until: datetime | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ActiveVersionResponse(BaseModel):
    id: uuid.UUID
    label: str | None = None
    status: str
    active_from: datetime | None = None
    sections: list[SectionWithConfig] = []

    model_config = {"from_attributes": True}
