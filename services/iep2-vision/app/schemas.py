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
from pydantic import BaseModel


class TrackingStartRequest(BaseModel):
    """Fully-resolved payload sent by EEP after DB lookups."""
    video_s3_key: str
    floor_plan_s3_key: Optional[str] = None
    homography_matrix: List[List[float]]
    zones: List[dict]
    pixels_per_meter: float = 100.0
    origin_px: Optional[dict] = None
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


class HealthResponse(BaseModel):
    service: str
    status: str
