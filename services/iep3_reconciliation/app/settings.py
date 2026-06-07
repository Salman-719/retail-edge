"""IEP3 settings — all configuration via environment variables.
Runtime never reads os.environ directly. Always use get_settings().
"""
from __future__ import annotations

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings


class Iep3Settings(BaseSettings):
    # ── Required ─────────────────────────────────────────────────────────────
    store_id:            str   = Field(...)
    window_seconds:      float = Field(..., gt=0)
    database_url_server: str   = Field(...)

    @field_validator("database_url_server")
    @classmethod
    def no_sqlalchemy_url(cls, v: str) -> str:
        if v.startswith("postgresql+"):
            raise ValueError(
                "database_url_server must use plain postgresql:// scheme, "
                "not postgresql+asyncpg:// — asyncpg is the direct driver here"
            )
        return v

    # ── Redis — server-side only (env: SERVER_REDIS_URL) ─────────────────────
    server_redis_url: str = Field(default="redis://redis:6379/0")

    # ── ReID parameters — every threshold configurable without code change ───
    reid_threshold:     float = Field(default=0.85, ge=0.0, le=1.0)
    max_speed_mps:      float = Field(default=1.5,  gt=0)
    grace_seconds:      float = Field(default=300.0, gt=0)
    embedding_dim:      int   = Field(default=2048, gt=0)
    centroid_ema_alpha: float = Field(default=0.3,  ge=0.0, le=1.0)

    # ── Coordinator ───────────────────────────────────────────────────────────
    coordinator_timeout_s: float = Field(default=120.0, gt=0)

    # ── Position selection weights — must sum to 1.0 ─────────────────────────
    position_weight_area: float = Field(default=0.7, ge=0.0, le=1.0)
    position_weight_conf: float = Field(default=0.3, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def weights_sum_to_one(self) -> "Iep3Settings":
        total = self.position_weight_area + self.position_weight_conf
        if abs(total - 1.0) > 0.01:
            raise ValueError(
                f"position_weight_area + position_weight_conf must equal 1.0, "
                f"got {total:.3f}"
            )
        return self

    # ── Resolution fallback ───────────────────────────────────────────────────
    default_frame_width:  int = Field(default=1920, gt=0)
    default_frame_height: int = Field(default=1080, gt=0)

    # ── Operational cadence ───────────────────────────────────────────────────
    expected_cameras_refresh_batches: int = Field(default=10, gt=0)
    orphan_sweep_interval_batches:    int = Field(default=50, gt=0)

    model_config = {"env_file": ".env", "extra": "ignore"}


def get_settings() -> Iep3Settings:
    """Construct and validate settings from environment variables.
    Raises ValidationError on missing or invalid required vars.
    Called once at startup — result passed to all components.
    """
    return Iep3Settings()
