"""IEP4 settings — all configuration via environment variables.
Runtime never reads os.environ directly. Always use get_settings().
"""
from __future__ import annotations

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings


class Iep4Settings(BaseSettings):
    # ── Required ─────────────────────────────────────────────────────────────
    store_id:            str = Field(...)
    database_url_server: str = Field(...)

    @field_validator("database_url_server")
    @classmethod
    def no_sqlalchemy_url(cls, v: str) -> str:
        if v.startswith("postgresql+"):
            raise ValueError(
                "database_url_server must use plain postgresql:// scheme — "
                "asyncpg is the direct driver here"
            )
        return v

    # ── Cadence / cursor ─────────────────────────────────────────────────────
    evaluation_batches:   int   = Field(default=5,  gt=0)   # wake every N batches
    max_lookback_batches: int   = Field(default=60, gt=0)   # cap replay on restart
    catchup_batch_size:   int   = Field(default=1,  gt=0)   # batches/cycle while behind
    # Batch length in seconds — batch_number is window_start_ms, so batches are
    # window_seconds apart. Used to convert batch counts <-> batch_number and to
    # pace the loop. Must match IEP1/IEP2/IEP3.
    window_seconds:       float = Field(default=60.0, gt=0)

    # ── Email (aiosmtplib) — optional so the daemon runs in dev without SMTP ──
    smtp_host:     str = Field(default="")
    smtp_port:     int = Field(default=587)
    smtp_user:     str = Field(default="")
    smtp_password: str = Field(default="")
    smtp_from:     str = Field(default="")
    # Bounded SMTP send so a slow/wedged mail server cannot stall the cycle.
    smtp_timeout_s: float = Field(default=10.0, gt=0)

    # development | production. In development, email delivery is skipped.
    environment: str = Field(default="production")

    model_config = {"env_file": ".env", "extra": "ignore"}

    @property
    def window_ms(self) -> int:
        return int(self.window_seconds * 1000)

    @property
    def email_enabled(self) -> bool:
        return bool(self.smtp_host) and self.environment != "development"


def get_settings() -> Iep4Settings:
    """Construct and validate settings from environment. Called once at startup."""
    return Iep4Settings()
