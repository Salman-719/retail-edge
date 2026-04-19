"""IEP1 — Ingestion Service: I/O contract.

All request bodies, query parameters, and response payloads are declared here so
every endpoint has an explicit, typed, documented contract. Field names match
the wire format 1:1 (no aliasing).

Endpoint catalogue
------------------

POST /ingest/{store_id}/cameras/{camera_id}/video
    Input :  multipart/form-data  file=<video binary>
    Output:  VideoUploadResponse            (200)
    Errors:  404 camera not found

POST /ingest/{store_id}/cameras/{camera_id}/chunk
    Query :  chunk_duration:int=300, overlap:int=30
    Output:  ChunkResponse                  (200)
    Errors:  404 camera / no video uploaded

GET  /ingest/{store_id}/cameras/{camera_id}/frame
    Query :  timestamp_sec:float=0.0
    Output:  image/jpeg bytes               (200)
    Errors:  400 unreadable frame, 404 camera / no video

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


# ── Video chunking ────────────────────────────────────────────────────────────

class ChunkInfo(BaseModel):
    """Metadata for a single chunk produced by the chunker."""
    chunk_idx: int = Field(..., ge=0)
    s3_key: str
    start_sec: float = Field(..., ge=0)
    end_sec: float = Field(..., ge=0)
    total_frames: int = Field(..., ge=0)
    accepted_frames: int = Field(..., ge=0, description="Frames that passed quality filter")
    rejected_frames: int = Field(..., ge=0, description="Frames rejected by quality filter")


class ChunkResponse(BaseModel):
    """Response body for the chunk endpoint."""
    camera_id: str
    chunks: List[ChunkInfo]
    total_chunks: int = Field(..., ge=0)
