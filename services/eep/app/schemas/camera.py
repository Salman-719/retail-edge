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
    # Method 2: calibration files data
    method: str = "homography"
    intrinsic_matrix: Optional[List[List[float]]] = None
    dist_coeffs: Optional[List[float]] = None
    rotation_matrix: Optional[List[List[float]]] = None
    translation_vector: Optional[List[float]] = None
    image_width: Optional[int] = None
    image_height: Optional[int] = None
    camera_world_x: Optional[float] = None
    camera_world_y: Optional[float] = None
    camera_world_z: Optional[float] = None

    model_config = {"from_attributes": True}


class CalibrationFilesRequest(BaseModel):
    """Parsed calibration data from intr_*.xml + extr_*.xml (Method 2)."""
    intrinsic_matrix: List[List[float]]       # 3×3 K
    dist_coeffs: List[float]                  # [k1, k2, p1, p2, k3, ...]
    rotation_matrix: List[List[float]]        # 3×3 R (post-Rodrigues)
    translation_vector: List[float]           # [tx, ty, tz]
    image_width: int
    image_height: int


class ParsedCalibrationResponse(BaseModel):
    """Response from the /parse endpoint — no DB write, just validation + parsed values."""
    intrinsic_matrix: List[List[float]]
    dist_coeffs: List[float]
    rotation_matrix: List[List[float]]
    translation_vector: List[float]
    image_width: int
    image_height: int
    camera_world_xyz: List[float]             # C = -R^T @ t
    warnings: List[str] = []


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
