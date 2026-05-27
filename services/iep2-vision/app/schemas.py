from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class Test1RunRequest(BaseModel):
    sample_rate_fps: float = Field(2.0, gt=0, le=30)
    max_frames_per_camera: int | None = Field(None, gt=0, le=100000)
    process_every_frame: bool = False
    match_threshold: float = Field(0.3, gt=0, lt=2)
    detector_backend: Literal["ultralytics_yolo", "yolox_mot", "rtdetr"] = "ultralytics_yolo"
    detector_model: str = "yolo11x.pt"
    detector_weights: str | None = None
    yolox_input_height: int = Field(800, gt=0, le=2048)
    yolox_input_width: int = Field(1440, gt=0, le=2560)
    nms_threshold: float = Field(0.7, ge=0.01, le=1)
    tracker_backend: Literal["boxmot_botsort", "ultralytics_botsort"] = "boxmot_botsort"
    tracker_config: str | None = None
    reid_backend: Literal["osnet", "resnet50", "descriptor"] = "osnet"
    reid_model: str = "osnet_x1_0"
    reid_weights: str | None = None
    confidence_threshold: float = Field(0.55, ge=0.01, le=1)
    duplicate_iou_threshold: float = Field(0.65, ge=0, le=1)
    duplicate_containment_threshold: float = Field(0.78, ge=0, le=1)
    min_detection_height_ratio: float = Field(0.12, ge=0, le=1)
    min_detection_aspect_ratio: float = Field(1.15, ge=0, le=10)
    min_cross_camera_observations: int = Field(3, ge=1, le=100)
    identity_gallery_size: int = Field(6, ge=1, le=32)
    annotated_stride: int = Field(10, gt=0, le=1000)
    device: str | None = None
    test1_dir: str | None = None


class RunStatusResponse(BaseModel):
    run_id: str
    status: Literal["queued", "running", "complete", "failed"]
    progress: float = 0.0
    frames_processed: int = 0
    frames_expected: int | None = None
    observations: int = 0
    identities: int = 0
    cameras: list[str] = []
    error: str | None = None
    artifact_dir: str | None = None


class RunArtifactsResponse(BaseModel):
    run_id: str
    artifact_dir: str
    files: list[dict[str, Any]]
