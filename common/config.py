"""Central configuration for the IEP2/IEP3 subsystem.

Every tunable parameter from the IEP2/IEP3 specs lives here so nothing is
hardcoded in business logic. Defaults match the specs' "Key Parameters" tables.

Repo reconciliation: this project's other service (EEP) and docker-compose use
*unprefixed* env vars (``DATABASE_URL``, ``REDIS_URL``), so this Settings object
reads the same names with no ``RV_`` prefix. ``extra="ignore"`` lets it coexist
with EEP's own env vars in a shared ``.env``.
"""

from __future__ import annotations

import os

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _database_url_default() -> str:
    """Build DATABASE_URL from individual RDS env vars (ECS Secrets Manager)
    or fall back to the full DATABASE_URL for local/docker-compose use."""
    host = os.getenv("DB_HOST")
    if host:
        user = os.getenv("DB_USER", "retailvision")
        pw = os.getenv("DB_PASS", "")
        port = os.getenv("DB_PORT", "5432")
        name = os.getenv("DB_NAME", "retailvision")
        return f"postgresql+asyncpg://{user}:{pw}@{host}:{port}/{name}"
    return os.getenv(
        "DATABASE_URL",
        "postgresql+asyncpg://retailvision:retailvision_dev@localhost:5432/retailvision",
    )


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # ---- Infrastructure ----
    DATABASE_URL: str = Field(default_factory=_database_url_default)
    REDIS_URL: str = Field(default="redis://localhost:6379/0")
    S3_ENDPOINT_URL: str = Field(default="http://localhost:9000")
    S3_PUBLIC_URL: str = Field(default="")
    S3_ACCESS_KEY: str = Field(default="retailvision")
    S3_SECRET_KEY: str = Field(default="retailvision_dev")
    S3_BUCKET: str = Field(default="retailvision")
    AWS_REGION: str | None = Field(default=None)
    AWS_SESSION_TOKEN: str | None = Field(default=None)
    db_pool_size: int = Field(default=10, ge=1, le=100)
    db_max_overflow: int = Field(default=20, ge=0, le=200)

    # ---- Identity / batch model ----
    batch_window_seconds: int = Field(default=60, ge=1)
    embedding_dim: int = Field(default=512, ge=1)  # read from the active model at startup
    gallery_max_size: int = Field(default=8, ge=1, le=64)
    global_gallery_max_size: int = Field(default=6, ge=1, le=64)
    init_embeddings_count: int = Field(default=5, ge=1)
    sample_interval_frames: int = Field(default=15, ge=1)

    # ---- ReID / spatial gates ----
    reid_match_threshold: float = Field(default=0.75, ge=0.0, le=2.0)  # cosine similarity
    max_walking_speed_mps: float = Field(default=1.5, gt=0.0)
    centroid_ema_alpha: float = Field(default=0.05, gt=0.0, lt=1.0)

    # ---- Quality gates (SampleEmbeddings) ----
    yolo_confidence_gate: float = Field(default=0.6, ge=0.0, le=1.0)
    track_age_gate_frames: int = Field(default=10, ge=0)
    min_bbox_area_px: int = Field(default=64 * 128, ge=1)

    # ---- TTL / grace ----
    lost_pool_ttl_batches: int = Field(default=5, ge=1)
    global_grace_batches: int = Field(default=5, ge=1)

    # ---- Position selection (IEP3) ----
    selection_weight_bbox_area: float = Field(default=0.7, ge=0.0, le=1.0)
    selection_weight_confidence: float = Field(default=0.3, ge=0.0, le=1.0)

    # ---- Persistence cadence ----
    position_flush_seconds: float = Field(default=2.0, gt=0.0)

    # ---- Detector / tracker / reid backends (M2) ----
    detector_backend: str = Field(default="yolo11")
    detector_model: str = Field(default="yolo11x.pt")
    detector_weights: str | None = Field(default=None)
    detector_allow_fallback: bool = Field(default=True)
    detector_fallback_model: str = Field(default="yolo11x.pt")
    detector_confidence: float = Field(default=0.55, ge=0.0, le=1.0)
    detector_nms_iou: float = Field(default=0.7, ge=0.0, le=1.0)
    yolox_input_height: int = Field(default=800, ge=64)
    yolox_input_width: int = Field(default=1440, ge=64)
    tracker_backend: str = Field(default="bytetrack")
    reid_backend: str = Field(default="osnet")
    reid_model: str = Field(default="osnet_x1_0")
    device: str | None = Field(default=None)  # None -> auto (cuda if available)

    # ---- Preprocessing (M2) ----
    duplicate_iou_threshold: float = Field(default=0.65, ge=0.0, le=1.0)
    duplicate_containment_threshold: float = Field(default=0.78, ge=0.0, le=1.0)
    min_detection_height_ratio: float = Field(default=0.12, ge=0.0, le=1.0)
    min_detection_aspect_ratio: float = Field(default=1.15, gt=0.0)

    # ---- ByteTrack params (M2) ----
    bytetrack_min_hits: int = Field(default=3, ge=1)
    bytetrack_max_age: int = Field(default=30, ge=1)
    bytetrack_track_thresh: float = Field(default=0.5, ge=0.0, le=1.0)
    bytetrack_match_thresh: float = Field(default=0.8, ge=0.0, le=1.0)

    # ---- Video ingest (M4) ----
    sample_rate_fps: float = Field(default=5.0, gt=0.0)
    iep1_jpeg_quality: int = Field(default=85, ge=1, le=100)
    iep1_s3_retry_attempts: int = Field(default=3, ge=1, le=10)
    online_frame_ratio: float = Field(default=1.0, ge=0.0, le=1.0)
    offline_frame_ratio: float = Field(default=0.1, ge=0.0, le=1.0)

    # ---- Logging ----
    log_level: str = Field(default="INFO")
    log_json: bool = Field(default=True)


_settings: Settings | None = None


def get_settings() -> Settings:
    """Singleton accessor. Import this, never instantiate Settings directly."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
