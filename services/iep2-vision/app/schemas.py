"""IEP2 — Vision Processing Service schemas.

Defines the clear input/output contract for every endpoint.

Endpoints:
  POST /tracking/{store_id}/cameras/{camera_id}/tracking/start
    Input:  TrackingStartRequest (JSON body)
    Output: TrackingStartResponse

  GET  /tracking/{store_id}/cameras/{camera_id}/tracking/stream
    Output: multipart/x-mixed-replace MJPEG stream

  GET  /tracking/{store_id}/cameras/{camera_id}/tracking/progress
    Output: TrackingProgressResponse

  GET  /tracking/{store_id}/cameras/{camera_id}/tracking/heatmap
    Output: image/png bytes

  GET  /tracking/{store_id}/cameras/{camera_id}/tracking/trajectory
    Output: TrajectoryResponse
"""
from typing import List, Dict, Optional
from pydantic import BaseModel, field_validator


class TrackingStartRequest(BaseModel):
    """Fully-resolved payload sent by EEP after DB lookups."""
    video_s3_key: str
    floor_plan_s3_key: Optional[str] = None
    # Projection method: 'homography' (Method 1) | 'calibration_files' (Method 2)
    projection_method: str = "homography"
    # Method 1: homography matrix
    homography_matrix: Optional[List[List[float]]] = None
    # Method 2: intrinsic/extrinsic calibration data
    intrinsic_matrix: Optional[List[List[float]]] = None
    dist_coeffs: Optional[List[float]] = None
    rotation_matrix: Optional[List[List[float]]] = None
    translation_vector: Optional[List[float]] = None
    # Common fields
    zones: List[dict]
    pixels_per_meter: Optional[float] = 100.0
    origin_px: Optional[dict] = None

    @field_validator("pixels_per_meter", mode="before")
    @classmethod
    def coerce_pixels_per_meter(cls, v):
        """Accept null/None from older EEP versions — fall back to 100.0."""
        return v if v is not None else 100.0
    world_bounds: Optional[dict] = None  # {x_min, x_max, y_min, y_max} for Method 2
    model_size: str = "yolov8n"
    store_id: str


class TrackingStartResponse(BaseModel):
    status: str  # "started" | "already_running"


class ZoneOccupancy(BaseModel):
    seconds: float
    percent: float


class TrackingProgressResponse(BaseModel):
    status: str  # "running" | "done" | "error" | "idle"
    progress: int  # 0-100
    total_frames: int
    zone_occupancy: Dict[str, ZoneOccupancy] = {}
    error: Optional[str] = None
    heatmap_url: Optional[str] = None


class TrajectoryPoint(BaseModel):
    frameIdx: int
    x: float
    y: float
    trackId: int


class TrajectoryResponse(BaseModel):
    trajectory: List[TrajectoryPoint] = []


class EnrollmentRequest(BaseModel):
    """Request to enroll an employee by extracting ReID embeddings from video."""
    video_s3_key: str
    employee_id: str
    store_id: str
    sample_count: int = 20  # number of crops to extract


class EnrollmentResponse(BaseModel):
    employee_id: str
    status: str  # "enrolled" | "failed"
    embedding_dim: int = 0
    samples_extracted: int = 0
    error: Optional[str] = None


class HealthResponse(BaseModel):
    service: str
    status: str
