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

    # ── Matcher parameters — spatial voting + Hungarian, appearance fallback ──
    # Stage 2 (spatial voting):
    vote_distance_threshold_m: float = Field(default=1.0, gt=0)   # max floor distance (m) to cast a vote
    min_vote_rate:             float = Field(default=0.6, ge=0.0, le=1.0)  # min votes/co_visible to confirm
    min_votes:                 int   = Field(default=10, ge=1)    # min raw vote count to trust any match
    temporal_tolerance_ms:     int   = Field(default=150, ge=0)   # max |T_a - T_b| to be co-visible
    ambiguity_margin:          float = Field(default=0.15, ge=0.0, le=1.0)  # vote_rate gap → appearance fires
    # Stage 3 (appearance fallback):
    reid_fallback_threshold:   float = Field(default=0.55, ge=0.0, le=1.0)  # median cosine to confirm
    # Shared:
    grace_seconds:  float = Field(default=300.0, gt=0)
    embedding_dim:  int   = Field(default=2048, gt=0)
    max_embeddings: int   = Field(default=10, ge=1)   # must match IEP2 MAX_EMBEDDINGS

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

    # ── Dev override — set by dev_orchestrator when fewer cameras than the full
    # active version are started. 0 means "resolve from DB" (production path). ──
    expected_cameras: int = Field(default=0, ge=0)

    model_config = {"env_file": ".env", "extra": "ignore"}


def get_settings() -> Iep3Settings:
    """Construct and validate settings from environment variables.
    Raises ValidationError on missing or invalid required vars.
    Called once at startup — result passed to all components.
    """
    return Iep3Settings()
