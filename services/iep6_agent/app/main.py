import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator

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

# Expose /metrics with a concurrency gauge so KEDA can scale the request-serving
# agent pods on actual in-flight OpenAI/API work instead of CPU.
Instrumentator(
    should_instrument_requests_inprogress=True,
    inprogress_name="http_requests_inprogress",
    inprogress_labels=False,
).instrument(app).expose(app, endpoint="/metrics")


@app.get("/health")
async def health():
    return {"service": "iep6_agent", "status": "ok"}
