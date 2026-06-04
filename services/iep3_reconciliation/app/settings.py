"""IEP3 settings — all configuration via environment variables.
Runtime never reads os.environ directly. Always use get_settings().
"""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Iep3Settings:
    # Database — plain postgresql:// (raw asyncpg, not SQLAlchemy format)
    database_url_server: str

    # Redis
    redis_url: str

    # Store identity
    store_id: str

    # Shared pipeline timing — must match IEP1 --window and IEP2 WINDOW_SECONDS
    window_seconds: float

    # Coordinator
    expected_cameras: frozenset
    coordinator_timeout_s: float

    # ReID
    reid_threshold: float
    max_speed_mps: float
    embedding_dim: int

    # Position selection weights
    selection_weight_area: float
    selection_weight_confidence: float

    # State machine
    grace_seconds: float

    # Resolution fallback
    default_frame_width: int
    default_frame_height: int


def get_settings() -> Iep3Settings:
    """Build Iep3Settings from environment variables.
    Raises ValueError on missing or invalid required vars.
    Called once at startup — result should be passed to all components.
    """
    database_url_server = os.environ.get("DATABASE_URL_SERVER", "")
    if not database_url_server:
        raise ValueError("DATABASE_URL_SERVER is required")
    if database_url_server.startswith("postgresql+"):
        raise ValueError(
            "DATABASE_URL_SERVER must use plain postgresql:// scheme, "
            "not postgresql+asyncpg:// — asyncpg is the direct driver here"
        )

    redis_url = os.environ.get("REDIS_URL", "redis://redis:6379/0")

    store_id = os.environ.get("STORE_ID", "")
    if not store_id:
        raise ValueError("STORE_ID is required")

    window_seconds_raw = os.environ.get("WINDOW_SECONDS", "")
    if not window_seconds_raw:
        raise ValueError("WINDOW_SECONDS is required — must match IEP1 --window and IEP2")
    window_seconds = float(window_seconds_raw)
    if window_seconds <= 0:
        raise ValueError(f"WINDOW_SECONDS must be > 0, got {window_seconds}")

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
        database_url_server=database_url_server,
        redis_url=redis_url,
        store_id=store_id,
        window_seconds=window_seconds,
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
