"""IEP5 settings — configuration via environment variables only."""
from __future__ import annotations

from datetime import date

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings


class Iep5Settings(BaseSettings):
    # ── Required ─────────────────────────────────────────────────────────────
    store_id:            str  = Field(...)
    shift_date:          date = Field(...)   # YYYY-MM-DD, always shift START date
    database_url_server: str  = Field(...)

    @field_validator("database_url_server")
    @classmethod
    def no_sqlalchemy_url(cls, v: str) -> str:
        if v.startswith("postgresql+"):
            raise ValueError("database_url_server must be plain postgresql:// (asyncpg)")
        return v

    # ── Tunables ─────────────────────────────────────────────────────────────
    heatmap_cell_size_m:     float = Field(default=0.5, gt=0)
    passthrough_dwell_ms:    int   = Field(default=30_000, ge=0)
    dead_period_threshold:   int   = Field(default=3, ge=0)
    dead_period_duration_ms: int   = Field(default=1_800_000, gt=0)

    model_config = {"env_file": ".env", "extra": "ignore"}


def get_settings() -> Iep5Settings:
    return Iep5Settings()
