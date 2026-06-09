import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from prometheus_client import make_asgi_app

from app import scheduler
from app.api.routers import agent
from app.core.config import settings

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.ENABLE_SCHEDULER:
        scheduler.start()
    try:
        yield
    finally:
        if settings.ENABLE_SCHEDULER:
            scheduler.shutdown()


app = FastAPI(title="IEP6 — Agent", lifespan=lifespan)
app.include_router(agent.router)
app.mount("/metrics", make_asgi_app())


@app.get("/health")
async def health():
    return {"service": "iep6_agent", "status": "ok"}
