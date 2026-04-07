"""IEP2 — Vision Processing Service (YOLO + ByteTrack)."""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_fastapi_instrumentator import Instrumentator

from app.core.s3_client import s3_client
from app.core.redis_client import async_redis
from app.core.database import engine

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("IEP2-vision starting…")
    s3_client.ensure_bucket()
    await async_redis.connect()
    logger.info("IEP2-vision ready.")
    yield
    await async_redis.close()
    await engine.dispose()
    logger.info("IEP2-vision shutdown.")


app = FastAPI(
    title="RetailVision IEP2 — Vision",
    version="1.0.0",
    description="YOLO+ByteTrack tracking, heatmap generation, per-camera job management.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

from app.api.tracking import router as tracking_router  # noqa: E402
app.include_router(tracking_router, prefix="/tracking", tags=["tracking"])

Instrumentator().instrument(app).expose(app, endpoint="/metrics")


@app.get("/health")
async def health():
    return {"service": "iep2-vision", "status": "ok"}
