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

    # ── Admin bootstrap (A3, optional) ───────────────────────────────────────
    # If BOTH are set and no super-admin exists yet, EEP seeds one on startup
    # (idempotent — no-op once an admin exists). Treat the password like
    # JWT_SECRET: never log it. Leave unset to provision admins via the CLI only.
    ADMIN_BOOTSTRAP_EMAIL: str | None = None
    ADMIN_BOOTSTRAP_PASSWORD: str | None = None

    # ── SMTP ─────────────────────────────────────────────────────────────────
    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = ""

    # ── gRPC TLS / Auth ──────────────────────────────────────────────────────
    GRPC_PORT: int = Field(default=50051)
    # Empty string = dev mode: gRPC runs insecure, auth is disabled.
    # Must be set to real cert paths in staging/production.
    GRPC_SERVER_CERT_PATH: str = Field(default="")
    GRPC_SERVER_KEY_PATH:  str = Field(default="")
    AGENT_SECRET: str = Field(default="")  # empty = dev mode (no auth check)

    # ── Analytics / heatmap ──────────────────────────────────────────────────
    # Heatmap grid cell size in world metres. SINGLE source of truth: the IEP5
    # launcher (iep5_manager) passes this to the writer and the analytics heatmap
    # endpoint reconstructs cell rectangles with the same value. They MUST match
    # or every cell is the wrong size. Matches IEP5's own default (0.5).
    HEATMAP_CELL_SIZE_M: float = 0.5

    # ── Live monitoring (F1) ─────────────────────────────────────────────────
    # A person counts as "present" only if last_seen_ts is within this window
    # (~2 IEP3/IEP4 windows). KPIs and the persons list use the SAME cut so the
    # numbers match the map dots.
    LIVE_STALE_MS: int = 120_000

    # ── Punch-in resolver (employee-linking) ─────────────────────────────────
    PUNCH_RESOLVER_INTERVAL_S: float = 20.0    # tick cadence
    PUNCH_SETTLE_MS: int = 90_000              # wait past T for IEP3 to reconcile the window
    PUNCH_MATCH_WINDOW_MS: int = 10_000        # ±window around T when matching positions
    PUNCH_MAX_WAIT_MS: int = 600_000           # give up after this -> status 'unmatched'

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
