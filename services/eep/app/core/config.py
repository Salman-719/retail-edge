import logging

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    # ── Database ─────────────────────────────────────────────────────────────
    # Required — no default. Must use postgresql+asyncpg:// (SQLAlchemy async).
    DATABASE_URL_EEP: str = Field(...)

    @field_validator("DATABASE_URL_EEP")
    @classmethod
    def must_be_sqlalchemy_asyncpg(cls, v: str) -> str:
        if not v.startswith("postgresql+asyncpg://"):
            raise ValueError(
                "DATABASE_URL_EEP must use postgresql+asyncpg:// format "
                "(SQLAlchemy asyncpg dialect). Got: " + v[:40]
            )
        return v

    # ── Window ───────────────────────────────────────────────────────────────
    # Required — no default. Must match IEP1 --window and IEP2/IEP3 batch window.
    WINDOW_SECONDS: float = Field(..., gt=0)

    # ── Redis ────────────────────────────────────────────────────────────────
    REDIS_URL: str = "redis://redis:6379/0"

    # ── S3 / MinIO ───────────────────────────────────────────────────────────
    S3_ENDPOINT_URL: str = "http://localhost:9000"
    S3_PUBLIC_URL: str = ""
    S3_ACCESS_KEY: str = Field(...)
    S3_SECRET_KEY: str = Field(...)
    S3_BUCKET: str = "retailvision"

    # ── Auth ─────────────────────────────────────────────────────────────────
    JWT_SECRET: str = Field(...)
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30

    # ── SMTP ─────────────────────────────────────────────────────────────────
    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = ""

    # ── Feature flags ────────────────────────────────────────────────────────
    # Explicit false default — never rely on absence of this var.
    DEBUG_MODE: bool = False

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()

logger.info(
    "EEP config resolved  window_seconds=%.1f  db_host=%s  debug_mode=%s",
    settings.WINDOW_SECONDS,
    settings.DATABASE_URL_EEP.split("@")[-1].split("/")[0],  # host only, no creds
    settings.DEBUG_MODE,
)
