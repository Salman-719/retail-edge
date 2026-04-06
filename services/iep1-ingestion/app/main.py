"""IEP1 — Data Ingestion Processor (Milestone 3+)."""
from fastapi import FastAPI

app = FastAPI(
    title="RetailVision IEP1 — Ingestion",
    version="0.1.0",
    description="Handles raw video ingestion, chunking, and backlog management. Placeholder — active in Milestone 3.",
)


@app.get("/health")
async def health():
    return {"service": "iep1-ingestion", "status": "ok", "milestone": "placeholder"}
