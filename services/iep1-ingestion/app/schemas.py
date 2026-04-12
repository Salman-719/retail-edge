"""IEP1 — Ingestion Service schemas.

Defines the clear input/output contract for every endpoint.

Endpoints:
  POST /ingest/{store_id}/cameras/{camera_id}/video
    Input:  multipart/form-data  file=<video>
    Output: VideoUploadResponse

  GET  /ingest/{store_id}/cameras/{camera_id}/frame?timestamp_sec=0.0
    Input:  query param timestamp_sec (float)
    Output: image/jpeg bytes
"""
from typing import Optional
from pydantic import BaseModel


class VideoUploadResponse(BaseModel):
    """Returned after a successful video upload and metadata extraction."""
    camera_id: str
    video_s3_key: str
    video_fps: float
    video_duration: float
    video_width: int
    video_height: int


class ChunkInfo(BaseModel):
    """Metadata for a single video chunk."""
    chunk_idx: int
    s3_key: str
    start_sec: float
    end_sec: float
    total_frames: int
    accepted_frames: int
    rejected_frames: int


class ChunkResponse(BaseModel):
    """Returned after video chunking."""
    camera_id: str
    chunks: list[ChunkInfo]
    total_chunks: int


class HealthResponse(BaseModel):
    service: str
    status: str
