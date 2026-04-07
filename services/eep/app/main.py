"""EEP — External Endpoint Processor (API Gateway)."""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from prometheus_fastapi_instrumentator import Instrumentator

from app.core.config import settings
from app.core.database import engine, Base
from app.core.s3_client import s3_client

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ──────────────────────────────────────────────────────────────
    logger.info("EEP starting — initialising infrastructure…")

    # Import all model modules so SQLAlchemy registers every table before create_all
    import app.models  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables ready.")

    s3_client.ensure_bucket()
    logger.info("S3 bucket ready.")

    yield

    # ── Shutdown ─────────────────────────────────────────────────────────────
    await engine.dispose()
    logger.info("EEP shutdown complete.")


app = FastAPI(
    title="RetailVision EEP",
    version="1.0.0",
    description="External Endpoint Processor — store onboarding, calibration, tracking.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from app.api import register_routers  # noqa: E402
register_routers(app)

Instrumentator().instrument(app).expose(app, endpoint="/metrics")


@app.get("/health")
async def health():
    return {"service": "eep", "status": "ok"}
