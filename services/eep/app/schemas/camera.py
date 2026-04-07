"""Camera and Calibration schemas."""
from __future__ import annotations
from typing import Optional, List, Any

from pydantic import BaseModel

from app.schemas.common import Point


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


class CorrespondencePoint(BaseModel):
    camPx: Point
    floorM: Point


class CalibrationRequest(BaseModel):
    correspondences: List[CorrespondencePoint]


class ProjectSave(BaseModel):
    """Bulk-save payload from the onboarding wizard (Step 8)."""
    floorPlan: Optional[dict] = None
    scale: Optional[dict] = None
    zones: Optional[List[dict]] = None
    obstacles: Optional[List[dict]] = None
    cameras: Optional[List[dict]] = None
