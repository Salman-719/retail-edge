import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import scheduler
from app.api.routers import agent

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler.start()
    try:
        yield
    finally:
        scheduler.shutdown()


app = FastAPI(title="IEP6 — Agent", lifespan=lifespan)
app.include_router(agent.router)


@app.get("/health")
async def health():
    return {"service": "iep6_agent", "status": "ok"}
