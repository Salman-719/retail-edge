"""IEP3 settings — all configuration via environment variables.
Runtime never reads os.environ directly. Always use get_settings().
"""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Iep3Settings:
    # Database
    database_url: str              # asyncpg DSN: postgresql://user:pass@host/db

    # Redis
    redis_url: str                 # redis://host:port/db

    # Store identity
    store_id: str                  # UUID of the store this IEP3 instance serves

    # Coordinator
    expected_cameras: frozenset    # frozenset[str] of camera_id strings
    coordinator_timeout_s: float   # seconds before partial reconciliation fires

    # ReID
    reid_threshold: float          # cosine similarity threshold
    max_speed_mps: float           # spatial gate max walking speed
    embedding_dim: int             # OSNet embedding dimension

    # Position selection weights
    selection_weight_area: float
    selection_weight_confidence: float

    # State machine
    grace_seconds: float           # LOST → EXITED after this many seconds

    # Resolution fallback
    default_frame_width: int
    default_frame_height: int


def get_settings() -> Iep3Settings:
    """Build Iep3Settings from environment variables.
    Raises ValueError on missing or invalid required vars.
    Called once at startup — result should be passed to all components.
    """
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url:
        raise ValueError("DATABASE_URL is required")
    if "+asyncpg" in database_url:
        raise ValueError(
            "DATABASE_URL must use plain postgresql:// scheme, "
            "not postgresql+asyncpg:// — asyncpg is the direct driver here"
        )

    redis_url = os.environ.get("REDIS_URL", "redis://redis:6379/0")

    store_id = os.environ.get("STORE_ID", "")
    if not store_id:
        raise ValueError("STORE_ID is required")

    cameras_raw = os.environ.get("EXPECTED_CAMERAS", "")
    if not cameras_raw:
        raise ValueError(
            "EXPECTED_CAMERAS is required — "
            "comma-separated list of camera_id strings"
        )
    expected_cameras = frozenset(
        c.strip() for c in cameras_raw.split(",") if c.strip()
    )

    return Iep3Settings(
        database_url=database_url,
        redis_url=redis_url,
        store_id=store_id,
        expected_cameras=expected_cameras,
        coordinator_timeout_s=float(os.environ.get("COORDINATOR_TIMEOUT_S", "120")),
        reid_threshold=float(os.environ.get("REID_THRESHOLD", "0.75")),
        max_speed_mps=float(os.environ.get("MAX_SPEED_MPS", "1.5")),
        embedding_dim=int(os.environ.get("EMBEDDING_DIM", "512")),
        selection_weight_area=float(os.environ.get("SELECTION_WEIGHT_AREA", "0.7")),
        selection_weight_confidence=float(os.environ.get("SELECTION_WEIGHT_CONFIDENCE", "0.3")),
        grace_seconds=float(os.environ.get("GRACE_SECONDS", "300.0")),
        default_frame_width=int(os.environ.get("DEFAULT_FRAME_WIDTH", "1920")),
        default_frame_height=int(os.environ.get("DEFAULT_FRAME_HEIGHT", "1080")),
    )
