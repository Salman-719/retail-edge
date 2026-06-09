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

# Expose /metrics WITH an in-flight request gauge (http_requests_inprogress) so the
# request-driven agent pods (ENABLE_SCHEDULER=false) can be KEDA-autoscaled on load.
# The agent is OpenAI/IO-bound, so concurrency — not CPU — is the right scale signal.
Instrumentator(
    should_instrument_requests_inprogress=True,
    inprogress_name="http_requests_inprogress",
    inprogress_labels=False,
).instrument(app).expose(app, endpoint="/metrics")


@app.get("/health")
async def health():
    return {"service": "iep6_agent", "status": "ok"}
