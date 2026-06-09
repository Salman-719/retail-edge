import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, field_validator, model_validator

from app.utils.intrinsics import ALLOWED_LENS_FOCAL_LENGTHS_MM


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
    store_id: uuid.UUID
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
    store_id: uuid.UUID
    name: str
    type: str
    points: list[list[float]]
    queue_threshold_people: int | None = None
    queue_threshold_minutes: int | None = None
    staff_absence_minutes: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

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
    store_id: uuid.UUID
    name: str | None = None
    points: list[list[float]]

    model_config = {"from_attributes": True}


# ─── Physical Cameras ─────────────────────────────────────────────────────────

def _validate_lens(v: float | None) -> float | None:
    if v is not None and v not in ALLOWED_LENS_FOCAL_LENGTHS_MM:
        raise ValueError(
            f"lens_focal_length_mm must be one of {list(ALLOWED_LENS_FOCAL_LENGTHS_MM)}"
        )
    return v


class CreateCameraRequest(BaseModel):
    name: str
    brand: str | None = None
    model: str | None = None
    mounting: str | None = "ceiling"
    cloud_stream_url: str | None = None
    stream_username: str | None = None
    stream_password: str | None = None
    lens_focal_length_mm: float | None = None
    h_fov_deg: float | None = None
    v_fov_deg: float | None = None
    stream_width: int | None = None
    stream_height: int | None = None

    _check_lens = field_validator("lens_focal_length_mm")(_validate_lens)


class PatchCameraRequest(BaseModel):
    name: str | None = None
    brand: str | None = None
    model: str | None = None
    mounting: str | None = None
    cloud_stream_url: str | None = None
    is_active: bool | None = None
    lens_focal_length_mm: float | None = None
    h_fov_deg: float | None = None
    v_fov_deg: float | None = None
    stream_width: int | None = None
    stream_height: int | None = None

    _check_lens = field_validator("lens_focal_length_mm")(_validate_lens)


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
    lens_focal_length_mm: float | None = None
    h_fov_deg: float | None = None
    v_fov_deg: float | None = None
    stream_width: int | None = None
    stream_height: int | None = None
    fx: float | None = None
    fy: float | None = None
    cx: float | None = None
    cy: float | None = None
    dist_coeffs: list[float] | None = None
    intrinsics_source: str | None = None

    model_config = {"from_attributes": True}


class CameraIntrinsicsResponse(BaseModel):
    """OpenCV-format intrinsics for consumption by IEP2 (M7-S2)."""
    camera_matrix: list[list[float]]
    dist_coeffs: list[float]
    source: str | None = None
    resolution: list[int | None]


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
    store_id: uuid.UUID
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


# ─── Punch-in station (employee-linking) ───────────────────────────────────────

class PunchStationRequest(BaseModel):
    camera_config_id: uuid.UUID
    position_x: float          # canvas px (converted to world metres for storage)
    position_y: float          # canvas px
    radius_m: float = 1.5

    @field_validator("radius_m")
    @classmethod
    def radius_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("radius_m must be > 0")
        return v


class PunchStationResponse(BaseModel):
    id: uuid.UUID
    version_id: uuid.UUID
    store_id: uuid.UUID
    camera_config_id: uuid.UUID
    camera_config_name: str | None = None
    position_x: float          # canvas px (converted back from stored world metres)
    position_y: float          # canvas px
    radius_m: float


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


class PnpCorrespondence(BaseModel):
    frame_px: float
    frame_py: float
    world_x: float
    world_y: float
    world_z: float = 0.0  # defaults to floor plane if not supplied


class PnpRequest(BaseModel):
    method: Literal["pnp"] = "pnp"
    correspondences: list[PnpCorrespondence]

    @field_validator("correspondences")
    @classmethod
    def min_six_points(cls, v: list[PnpCorrespondence]) -> list[PnpCorrespondence]:
        if len(v) < 6:
            raise ValueError("at least 6 correspondence points required")
        return v


class CameraPositionWorld(BaseModel):
    x: float
    y: float
    z: float


class PnpCalibrationResponse(BaseModel):
    calibration_id: uuid.UUID
    method: str
    status: str
    rms_reprojection_error: float
    max_reprojection_error: float
    point_count: int
    quality: str
    camera_position_world: CameraPositionWorld


class ProjectPointRequest(BaseModel):
    frame_px: float
    frame_py: float


class ProjectPointResponse(BaseModel):
    method: str | None = None
    world_x: float | None = None    # world metres
    world_y: float | None = None    # world metres
    map_px:  float | None = None    # canvas pixels (TPS: converted from world; others: passthrough)
    map_py:  float | None = None    # canvas pixels


# ─── TPS Calibration ──────────────────────────────────────────────────────────

class TpsCorrespondence(BaseModel):
    frame_px: float
    frame_py: float
    map_px:   float
    map_py:   float


class TpsRequest(BaseModel):
    correspondences: list[TpsCorrespondence]


class TpsCalibrationResponse(BaseModel):
    calibration_id: uuid.UUID
    method: str
    status: str
    coverage_score: float
    point_count: int
    quality: str    # "excellent" | "good"


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
