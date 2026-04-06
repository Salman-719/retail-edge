"""EEP — External Endpoint Processor (API Gateway)."""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.database import engine, Base
from app.core.s3_client import s3_client

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ──────────────────────────────────────────────────────────────
    logger.info("EEP starting — initialising infrastructure…")

    # Create all DB tables (Alembic handles migrations in prod; this covers dev)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables ready.")

    # Ensure MinIO bucket exists
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

# ── Routers ──────────────────────────────────────────────────────────────────
from app.api import stores, floor_plans, zones, cameras, calibration, tracking  # noqa: E402

app.include_router(stores.router, prefix="/api/stores", tags=["stores"])
app.include_router(floor_plans.router, prefix="/api/stores", tags=["floor-plans"])
app.include_router(zones.router, prefix="/api/stores", tags=["zones"])
app.include_router(cameras.router, prefix="/api/stores", tags=["cameras"])
app.include_router(calibration.router, prefix="/api/stores", tags=["calibration"])
app.include_router(tracking.router, prefix="/api/stores", tags=["tracking"])


@app.get("/health")
async def health():
    return {"service": "eep", "status": "ok"}
