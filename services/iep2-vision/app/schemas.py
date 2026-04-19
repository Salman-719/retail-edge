"""IEP2 — Vision Processing Service: I/O contract.

All request bodies, query parameters, and response payloads are declared here so
every endpoint has an explicit, typed, documented contract.

Wire-compatibility notes
------------------------
- `TrajectoryPoint` uses camelCase fields (`frameIdx`, `trackId`) for
  direct consumption by the React frontend (Step9_TestMode, live monitoring
  canvas). All other models are snake_case.

Endpoint catalogue
------------------

POST /tracking/{store_id}/cameras/{camera_id}/tracking/start
    Input :  TrackingStartRequest
    Query :  model_size:str="yolov8n"         (override)
    Output:  TrackingStartResponse            (200)
    Errors:  —  (any I/O failure bubbles as 500)

GET  /tracking/{store_id}/cameras/{camera_id}/tracking/stream
    Output:  multipart/x-mixed-replace MJPEG  (200)
    Errors:  404 no job for camera

GET  /tracking/{store_id}/cameras/{camera_id}/tracking/progress
    Output:  TrackingProgressResponse         (200)
    Errors:  404 no job for camera

GET  /tracking/{store_id}/cameras/{camera_id}/tracking/heatmap
    Output:  image/png bytes                  (200)
    Errors:  404 heatmap not yet available

GET  /tracking/{store_id}/cameras/{camera_id}/tracking/trajectory
    Output:  TrajectoryResponse               (200)
    Errors:  404 no job for camera

POST /enrollment/{store_id}/employees/{employee_id}/enroll
    Input :  EnrollmentRequest
    Output:  EnrollmentResponse               (200)
    Errors:  404 enrollment video not found

GET  /health
    Output:  HealthResponse                   (200)
"""
from typing import List, Dict, Optional, Literal
from pydantic import BaseModel, Field, field_validator


# ── Health ────────────────────────────────────────────────────────────────────

class HealthResponse(BaseModel):
    service: str = "iep2-vision"
    status: str = "ok"


# ── Shared primitives ─────────────────────────────────────────────────────────

class Point(BaseModel):
    """2-D point. Used for polygon vertices and pixel anchors."""
    x: float
    y: float


class Zone(BaseModel):
    """Polygon zone definition passed from EEP at tracking start."""
    name: str
    type: Optional[str] = Field(None, description='e.g. "entrance", "checkout", "general"')
    points: List[Point] = Field(..., description="Polygon vertices (metres or pixels per context)")


class ZoneOccupancy(BaseModel):
    """Dwell statistics for a single zone during a tracking run."""
    seconds: float = Field(..., ge=0)
    percent: float = Field(..., ge=0, le=100)


# ── Tracking ──────────────────────────────────────────────────────────────────

ProjectionMethod = Literal["homography", "calibration_files"]
JobStatus = Literal["idle", "running", "done", "error"]
StartStatus = Literal["started", "already_running"]


class TrackingStartRequest(BaseModel):
    """Fully-resolved payload sent by EEP after DB lookups."""
    video_s3_key: str
    floor_plan_s3_key: Optional[str] = None

    # Projection method selector
    projection_method: ProjectionMethod = "homography"

    # Method 1 — homography matrix (3x3)
    homography_matrix: Optional[List[List[float]]] = None

    # Method 2 — intrinsic/extrinsic calibration
    intrinsic_matrix: Optional[List[List[float]]] = None
    dist_coeffs: Optional[List[float]] = None
    rotation_matrix: Optional[List[List[float]]] = None
    translation_vector: Optional[List[float]] = None

    # Common
    zones: List[Zone] = Field(default_factory=list)
    pixels_per_meter: Optional[float] = 100.0
    origin_px: Optional[Point] = None
    world_bounds: Optional[Dict[str, float]] = Field(
        None, description='Method-2 only: {"x_min","x_max","y_min","y_max"}'
    )
    model_size: str = "yolov8n"
    store_id: str

    @field_validator("pixels_per_meter", mode="before")
    @classmethod
    def _coerce_ppm(cls, v):
        """Accept null/None from older EEP versions — fall back to 100.0."""
        return v if v is not None else 100.0


class TrackingStartResponse(BaseModel):
    status: StartStatus


class TrackingProgressResponse(BaseModel):
    """Snapshot of a running or completed tracking job."""
    status: JobStatus
    progress: int = Field(..., ge=0, le=100, description="Percent complete")
    total_frames: int = Field(..., ge=0)
    zone_occupancy: Dict[str, ZoneOccupancy] = Field(default_factory=dict)
    error: Optional[str] = None
    heatmap_url: Optional[str] = None


class TrajectoryPoint(BaseModel):
    """One point in a person trajectory. CamelCase for frontend consumption."""
    frameIdx: int
    x: float
    y: float
    trackId: int


class TrajectoryResponse(BaseModel):
    trajectory: List[TrajectoryPoint] = Field(default_factory=list)


# ── Enrollment ────────────────────────────────────────────────────────────────

EnrollmentStatus = Literal["enrolled", "failed"]


class EnrollmentRequest(BaseModel):
    """Request to enroll an employee by extracting ReID embeddings."""
    video_s3_key: str
    employee_id: str
    store_id: str
    sample_count: int = Field(20, ge=1, description="Number of crops to extract")


class EnrollmentResponse(BaseModel):
    employee_id: str
    status: EnrollmentStatus
    embedding_dim: int = Field(0, ge=0)
    samples_extracted: int = Field(0, ge=0)
    error: Optional[str] = None
