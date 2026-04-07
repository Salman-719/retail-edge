"""IEP1 — Data Ingestion Processor.

Responsibilities:
  - Video upload, metadata extraction (fps, duration, dimensions)
  - Video storage in S3
  - Frame extraction from stored video
  - (Milestone 3+) RTSP chunking, backlog management
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_fastapi_instrumentator import Instrumentator

from app.core.s3_client import s3_client
from app.core.database import engine

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("IEP1-ingestion starting…")
    s3_client.ensure_bucket()
    logger.info("IEP1-ingestion ready.")
    yield
    await engine.dispose()
    logger.info("IEP1-ingestion shutdown.")


app = FastAPI(
    title="RetailVision IEP1 — Ingestion",
    version="1.0.0",
    description="Video ingestion, metadata extraction, and frame serving.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

from app.api.videos import router as videos_router  # noqa: E402
app.include_router(videos_router, prefix="/ingest", tags=["videos"])

Instrumentator().instrument(app).expose(app, endpoint="/metrics")


@app.get("/health")
async def health():
    return {"service": "iep1-ingestion", "status": "ok"}
