"""Pydantic request/response schemas for all EEP endpoints."""
from __future__ import annotations
from datetime import datetime
from typing import Optional, List, Any

from pydantic import BaseModel, field_validator


# ─── Common ───────────────────────────────────────────────────────────────────

class HealthResponse(BaseModel):
    status: str
    service: str
    version: str = "1.0.0"


class Point(BaseModel):
    x: float
    y: float


# ─── Store ────────────────────────────────────────────────────────────────────

class StoreCreate(BaseModel):
    name: str


class StoreResponse(BaseModel):
    id: str
    name: str
    created_at: datetime

    model_config = {"from_attributes": True}


# ─── Floor Plan ───────────────────────────────────────────────────────────────

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


# ─── Zone ─────────────────────────────────────────────────────────────────────

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


# ─── Obstacle ─────────────────────────────────────────────────────────────────

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


# ─── Camera ───────────────────────────────────────────────────────────────────

class CameraCreate(BaseModel):
    id: Optional[str] = None
    name: str
    position_x: Optional[float] = None
    position_y: Optional[float] = None
    height_meters: Optional[float] = None
    rtsp_url: Optional[str] = None


class CameraUpdate(BaseModel):
    name: Optional[str] = None
    position_x: Optional[float] = None
    position_y: Optional[float] = None
    height_meters: Optional[float] = None
    rtsp_url: Optional[str] = None


class CalibrationResponse(BaseModel):
    id: str
    camera_id: str
    correspondences: Optional[List[Any]] = None
    homography_matrix: Optional[List[List[float]]] = None
    reprojection_error: Optional[float] = None
    status: Optional[str] = None

    model_config = {"from_attributes": True}


class CameraResponse(BaseModel):
    id: str
    store_id: str
    name: str
    position_x: Optional[float] = None
    position_y: Optional[float] = None
    height_meters: Optional[float] = None
    rtsp_url: Optional[str] = None
    video_duration: Optional[float] = None
    video_fps: Optional[float] = None
    video_width: Optional[int] = None
    video_height: Optional[int] = None
    calibration: Optional[CalibrationResponse] = None

    model_config = {"from_attributes": True}


# ─── Calibration ──────────────────────────────────────────────────────────────

class CorrespondencePoint(BaseModel):
    camPx: Point
    floorM: Point


class CalibrationRequest(BaseModel):
    correspondences: List[CorrespondencePoint]


# ─── Project export (backward-compat bulk save) ───────────────────────────────

class ProjectSave(BaseModel):
    """The wizard sends the entire project state in a single call for bulk save."""
    floorPlan: Optional[dict] = None
    scale: Optional[dict] = None
    zones: Optional[List[dict]] = None
    obstacles: Optional[List[dict]] = None
    cameras: Optional[List[dict]] = None
