"""IEP6 (AI agent) configuration. Mirrors the EEP settings pattern."""
import logging

from pydantic import Field
from pydantic_settings import BaseSettings

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    # ── Database (READ-ONLY analytics connection) ─────────────────────────────
    # Use a read-only Postgres role (retailvision_ro). asyncpg dialect.
    DATABASE_URL_AGENT: str = Field(...)

    # ── Redis ─────────────────────────────────────────────────────────────────
    REDIS_URL: str = "redis://redis:6379/0"

    # ── OpenAI ────────────────────────────────────────────────────────────────
    OPENAI_API_KEY: str = Field(...)
    OPENAI_MODEL: str = "gpt-4o-mini"
    OPENAI_MAX_TOKENS: int = 800
    AGENT_MAX_TOOL_STEPS: int = 6  # cap the function-calling loop (cost guard)

    # ── EEP (for actions) ─────────────────────────────────────────────────────
    EEP_BASE_URL: str = "http://eep-http:8000"
    JWT_SECRET: str = Field(...)
    JWT_ALGORITHM: str = "HS256"
    EEP_SERVICE_USER_ID: str = ""  # service principal UUID EEP accepts for actions

    # ── SMTP (insight/alert delivery) ─────────────────────────────────────────
    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = ""

    # ── Feature gates (safety) ────────────────────────────────────────────────
    ENABLE_RAW_SQL: bool = False       # the run_readonly_sql escape-hatch tool
    ENABLE_EEP_ACTIONS: bool = False   # the eep_action tool (writes); default read-only
    SQL_STATEMENT_TIMEOUT_MS: int = 8000

    # ── Schedules ─────────────────────────────────────────────────────────────
    INSIGHTS_CRON_HOUR: int = 6        # daily insight report hour (UTC)
    ALERT_POLL_INTERVAL_S: int = 300   # proactive-alert poll cadence
    ENABLE_SCHEDULER: bool = True      # keep one scheduler-enabled replica

    WINDOW_SECONDS: float = 60.0
    DEBUG_MODE: bool = False

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()

logger.info(
    "IEP6 config resolved  model=%s  raw_sql=%s  eep_actions=%s",
    settings.OPENAI_MODEL, settings.ENABLE_RAW_SQL, settings.ENABLE_EEP_ACTIONS,
)
