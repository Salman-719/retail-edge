import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, field_validator, model_validator


# ─── Draft Version ────────────────────────────────────────────────────────────

class CreateDraftRequest(BaseModel):
    label: str | None = None
    clone_from_active: bool = False


class DraftVersionResponse(BaseModel):
    id: uuid.UUID
    store_id: uuid.UUID
    label: str | None = None
    status: str
    created_by: uuid.UUID
    created_at: datetime
    last_edited_at: datetime

    model_config = {"from_attributes": True}


# ─── Floor Plan ───────────────────────────────────────────────────────────────

class FloorPlanUploadResponse(BaseModel):
    id: uuid.UUID
    version_id: uuid.UUID
    section_id: uuid.UUID
    onboarding_method: str
    display_url: str | None = None
    width_px: int | None = None
    height_px: int | None = None
    image_uploaded: bool
    scale_defined: bool

    model_config = {"from_attributes": True}


class FloorPlanDetailResponse(FloorPlanUploadResponse):
    origin_x: float | None = None
    origin_y: float | None = None
    pixels_per_meter: float | None = None
    world_x_min: float | None = None
    world_x_max: float | None = None
    world_y_min: float | None = None
    world_y_max: float | None = None
    boundary_polygon: list[list[float]] | None = None

    model_config = {"from_attributes": True}


class ScaleRequest(BaseModel):
    origin_x: float
    origin_y: float
    ref_point_1: list[float]
    ref_point_2: list[float]
    real_distance_meters: float
    boundary_polygon: list[list[float]] | None = None

    @field_validator("ref_point_1", "ref_point_2")
    @classmethod
    def must_be_two_coords(cls, v: list[float]) -> list[float]:
        if len(v) != 2:
            raise ValueError("must be [x, y]")
        return v


class WorldBoundsRequest(BaseModel):
    world_x_min: float
    world_x_max: float
    world_y_min: float
    world_y_max: float


# ─── Zones ────────────────────────────────────────────────────────────────────

class ZoneCreate(BaseModel):
    name: str
    type: str
    points: list[list[float]]
    queue_threshold_people: int | None = None
    queue_threshold_minutes: int | None = None
    staff_absence_minutes: int | None = None

    @field_validator("points")
    @classmethod
    def min_three_points(cls, v: list[list[float]]) -> list[list[float]]:
        if len(v) < 3:
            raise ValueError("zone must have at least 3 points")
        return v

    @field_validator("type")
    @classmethod
    def valid_type(cls, v: str) -> str:
        allowed = {"entrance", "checkout", "aisle", "staff_only", "general"}
        if v not in allowed:
            raise ValueError(f"type must be one of {allowed}")
        return v


class ZoneUpdate(BaseModel):
    name: str | None = None
    type: str | None = None
    points: list[list[float]] | None = None
    queue_threshold_people: int | None = None
    queue_threshold_minutes: int | None = None
    staff_absence_minutes: int | None = None

    @field_validator("points")
    @classmethod
    def min_three_points(cls, v: list[list[float]] | None) -> list[list[float]] | None:
        if v is not None and len(v) < 3:
            raise ValueError("zone must have at least 3 points")
        return v


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


# ─── Obstacles ────────────────────────────────────────────────────────────────

class ObstacleCreate(BaseModel):
    name: str | None = None
    points: list[list[float]]

    @field_validator("points")
    @classmethod
    def min_three_points(cls, v: list[list[float]]) -> list[list[float]]:
        if len(v) < 3:
            raise ValueError("obstacle must have at least 3 points")
        return v


class ObstacleUpdate(BaseModel):
    name: str | None = None
    points: list[list[float]] | None = None

    @field_validator("points")
    @classmethod
    def min_three_points(cls, v: list[list[float]] | None) -> list[list[float]] | None:
        if v is not None and len(v) < 3:
            raise ValueError("obstacle must have at least 3 points")
        return v


class ObstacleResponse(BaseModel):
    id: uuid.UUID
    version_id: uuid.UUID
    section_id: uuid.UUID
    name: str | None = None
    points: list[list[float]]

    model_config = {"from_attributes": True}


# ─── Physical Cameras ─────────────────────────────────────────────────────────

class CreateCameraRequest(BaseModel):
    name: str
    brand: str | None = None
    model: str | None = None
    mounting: str | None = "ceiling"
    cloud_stream_url: str | None = None
    stream_username: str | None = None
    stream_password: str | None = None


class PatchCameraRequest(BaseModel):
    name: str | None = None
    brand: str | None = None
    model: str | None = None
    mounting: str | None = None
    cloud_stream_url: str | None = None
    is_active: bool | None = None


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


# ─── Camera Configs ───────────────────────────────────────────────────────────

class PlaceCameraConfigRequest(BaseModel):
    physical_camera_id: uuid.UUID
    position_x: float
    position_y: float
    height_meters: float | None = None
    fov_deg: float | None = None


class UpdateCameraConfigRequest(BaseModel):
    position_x: float | None = None
    position_y: float | None = None
    height_meters: float | None = None
    fov_deg: float | None = None


class CameraConfigResponse(BaseModel):
    id: uuid.UUID
    version_id: uuid.UUID
    physical_camera_id: uuid.UUID
    physical_camera_name: str
    section_id: uuid.UUID
    position_x: float
    position_y: float
    height_meters: float | None = None
    fov_deg: float | None = None
    stream_url: str | None = None
    frame_url: str | None = None
    frame_captured_at: datetime | None = None
    status: str

    model_config = {"from_attributes": True}


class FrameUploadResponse(BaseModel):
    config_id: uuid.UUID
    frame_url: str
    frame_captured_at: datetime
    status: str


# ─── Calibration ──────────────────────────────────────────────────────────────

class Correspondence(BaseModel):
    pixel: list[float]
    world: list[float]

    @field_validator("pixel", "world")
    @classmethod
    def must_be_two_coords(cls, v: list[float]) -> list[float]:
        if len(v) != 2:
            raise ValueError("must be [x, y]")
        return v


class HomographyRequest(BaseModel):
    correspondences: list[Correspondence]

    @field_validator("correspondences")
    @classmethod
    def min_eight_pairs(cls, v: list[Correspondence]) -> list[Correspondence]:
        if len(v) < 8:
            raise ValueError("at least 8 point correspondences required")
        return v


class CalibrationResponse(BaseModel):
    id: uuid.UUID
    camera_config_id: uuid.UUID
    method: str
    status: str
    is_current: bool
    correspondences: list | None = None
    homography_matrix: list | None = None
    rms_reprojection_error: float | None = None
    max_reprojection_error: float | None = None
    point_count: int | None = None
    coverage_score: float | None = None
    condition_number: float | None = None
    intrinsic_matrix: list | None = None
    computed_at: datetime | None = None
    verified_at: datetime | None = None

    model_config = {"from_attributes": True}


# ─── Sections (draft CRUD) ────────────────────────────────────────────────────

class CreateSectionRequest(BaseModel):
    name: str
    type: str = "floor"
    display_order: int = 0


class PatchSectionRequest(BaseModel):
    name: str | None = None
    type: str | None = None
    display_order: int | None = None


class SectionResponse(BaseModel):
    id: uuid.UUID
    store_id: uuid.UUID
    name: str
    type: str
    display_order: int
    is_default: bool
    status: str

    model_config = {"from_attributes": True}


# ─── Activation ───────────────────────────────────────────────────────────────

class ActivateDraftRequest(BaseModel):
    countdown_sec: int = 30
    label: str | None = None


class VersionActivateRequest(BaseModel):
    mode: Literal["immediate", "scheduled"]
    activate_at: datetime | None = None  # required if mode='scheduled', UTC

    @model_validator(mode="after")
    def validate_scheduled(self) -> "VersionActivateRequest":
        if self.mode == "scheduled" and self.activate_at is None:
            raise ValueError("activate_at required when mode is 'scheduled'")
        if self.mode == "scheduled" and self.activate_at <= datetime.now(timezone.utc):
            raise ValueError("activate_at must be in the future")
        return self


class VersionActivateResponse(BaseModel):
    version_id: uuid.UUID
    status: str                      # 'activating' | 'scheduled'
    activate_at: datetime | None = None
    cameras_restarted: list[uuid.UUID] = []   # physical_camera_ids — immediate only
    cameras_pending: list[uuid.UUID] = []     # physical_camera_ids with open sessions


class SyncEventResponse(BaseModel):
    id: uuid.UUID
    store_id: uuid.UUID
    version_id: uuid.UUID
    status: str
    scheduled_at: datetime
    executed_at: datetime | None = None
    remaining_seconds: float | None = None
    countdown_sec: int | None = None

    model_config = {"from_attributes": True}
