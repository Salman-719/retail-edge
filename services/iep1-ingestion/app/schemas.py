"""IEP1 — Ingestion Service: I/O contract.

All request bodies, query parameters, and response payloads are declared here so
every endpoint has an explicit, typed, documented contract. Field names match
the wire format 1:1 (no aliasing).

Endpoint catalogue
------------------

POST /ingest/{store_id}/cameras/{camera_id}/video
    Input :  multipart/form-data  file=<video binary>
    Output:  FrameExtractionResponse        (200)
    Errors:  404 camera not found

GET  /health
    Output:  HealthResponse                 (200)
"""
from typing import List
from pydantic import BaseModel, Field


# ── Health ────────────────────────────────────────────────────────────────────

class HealthResponse(BaseModel):
    service: str = "iep1-ingestion"
    status: str = "ok"


# ── Video upload ──────────────────────────────────────────────────────────────

class VideoUploadResponse(BaseModel):
    """Returned after a successful video upload and metadata extraction."""
    camera_id: str
    video_s3_key: str = Field(..., description="S3 object key the video was stored under")
    video_fps: float = Field(..., ge=0, description="Frames per second")
    video_duration: float = Field(..., ge=0, description="Duration in seconds")
    video_width: int = Field(..., ge=0)
    video_height: int = Field(..., ge=0)


# ── Frame extraction (5 fps sampling) ────────────────────────────────────────

class FrameInfo(BaseModel):
    """Metadata for a single sampled frame."""
    frame_index: int = Field(..., ge=0, description="0-based index in the sampled sequence")
    timestamp_sec: float = Field(..., ge=0, description="Position in source video (seconds)")
    s3_key: str = Field(..., description="S3 key of the stored JPEG, e.g. stores/{store_id}/cameras/{camera_id}/frames/frame_0042.jpg")


class FrameExtractionResponse(BaseModel):
    """Returned after a successful video upload and 5-fps frame sampling."""
    camera_id: str
    video_s3_key: str = Field(..., description="S3 key of the original uploaded video")
    source_fps: float = Field(..., ge=0, description="Original video frame rate")
    sample_fps: float = Field(5.0, description="Sampling rate applied (always 5.0)")
    video_duration: float = Field(..., ge=0, description="Duration in seconds")
    video_width: int = Field(..., ge=0)
    video_height: int = Field(..., ge=0)
    frames: List[FrameInfo]
    total_frames: int = Field(..., ge=0, description="Number of sampled frames = len(frames)")


# ── Video chunking ────────────────────────────────────────────────────────────

class ChunkInfo(BaseModel):
    """Metadata for a single video chunk stored in S3."""
    chunk_idx: int = Field(..., ge=0)
    s3_key: str
    start_sec: float = Field(..., ge=0)
    end_sec: float = Field(..., ge=0)
    total_frames: int = Field(..., ge=0)
    accepted_frames: int = Field(..., ge=0)
    rejected_frames: int = Field(..., ge=0)


class ChunkResponse(BaseModel):
    """Returned after splitting a video into chunks."""
    camera_id: str
    chunks: List[ChunkInfo]
    total_chunks: int = Field(..., ge=0)
