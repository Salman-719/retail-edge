"""IEP2 — Vision Processing Service: I/O contract.

All request bodies, query parameters, and response payloads are declared here so
every endpoint has an explicit, typed, documented contract.

Endpoint catalogue
------------------

POST /tracking/{store_id}/cameras/{camera_id}/tracking/start
    Input :  TrackingStartRequest  (list of frame S3 keys from IEP1 + calibration)
    Output:  TrackingStartResponse            (200)
    Errors:  —  (any I/O failure bubbles as 500)

GET  /tracking/{store_id}/cameras/{camera_id}/tracking/progress
    Output:  TrackingProgressResponse         (200)
    Errors:  404 no job for camera

POST /enrollment/{store_id}/employees/{employee_id}/enroll
    Input :  EnrollmentRequest
    Output:  EnrollmentResponse               (200)
    Errors:  404 enrollment frames not found

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


# ── Tracking ──────────────────────────────────────────────────────────────────

ProjectionMethod = Literal["homography", "calibration_files"]
JobStatus = Literal["idle", "running", "done", "error"]
StartStatus = Literal["started", "already_running"]


class TrackingStartRequest(BaseModel):
    """Sent by EEP to start a tracking job on a video uploaded via IEP1."""
    video_s3_key: str = Field(..., description="S3 key of the uploaded video produced by IEP1")
    store_id: str
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
    error: Optional[str] = None
    zone_occupancy: Optional[Dict[str, dict]] = None
    heatmap_url: Optional[str] = None


# ── Per-frame DB record ───────────────────────────────────────────────────────

class DetectionRecord(BaseModel):
    """One YOLO+ByteTrack detection within a single frame."""
    track_id: int = Field(..., description="ByteTrack persistent person ID")
    bbox_x: float = Field(..., description="Bounding-box centre X (pixels)")
    bbox_y: float = Field(..., description="Bounding-box centre Y (pixels)")
    bbox_w: float = Field(..., ge=0, description="Bounding-box width (pixels)")
    bbox_h: float = Field(..., ge=0, description="Bounding-box height (pixels)")
    confidence: float = Field(..., ge=0, le=1)
    floor_x: Optional[float] = Field(None, description="Projected floor position X (metres)")
    floor_y: Optional[float] = Field(None, description="Projected floor position Y (metres)")
    zone_name: Optional[str] = Field(None, description="Zone the person is standing in")


class FrameRecord(BaseModel):
    """Complete per-frame row written to the database by IEP2."""
    store_id: str
    camera_id: str
    frame_index: int = Field(..., ge=0)
    timestamp_sec: float = Field(..., ge=0)
    s3_key: str = Field(..., description="Source JPEG S3 key (from IEP1)")
    detections: List[DetectionRecord] = Field(default_factory=list)
    people_count: int = Field(..., ge=0, description="Number of tracked persons in this frame")


# ── Trajectory ───────────────────────────────────────────────────────────────

class TrajectoryPoint(BaseModel):
    frameIdx: int
    x: float
    y: float
    trackId: int
    personType: str
    employeeId: Optional[str] = None


class TrajectoryResponse(BaseModel):
    trajectory: List[TrajectoryPoint]


# ── Enrollment ────────────────────────────────────────────────────────────────

EnrollmentStatus = Literal["enrolled", "failed"]


class EnrollmentRequest(BaseModel):
    """Request to enroll an employee using a video uploaded via IEP1."""
    video_s3_key: str = Field(..., description="S3 key of the enrollment video")
    employee_id: str
    store_id: str
    sample_count: int = Field(20, ge=1, description="Number of crops to extract")


class EnrollmentResponse(BaseModel):
    employee_id: str
    status: EnrollmentStatus
    embedding_dim: int = Field(0, ge=0)
    samples_extracted: int = Field(0, ge=0)
    error: Optional[str] = None
