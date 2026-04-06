"""IEP4 — Analytics Aggregation (Milestone 3+)."""
from fastapi import FastAPI

app = FastAPI(
    title="RetailVision IEP4 — Analytics",
    version="0.1.0",
    description="Aggregates tracking data into time-series analytics and reports. Placeholder — active in Milestone 3.",
)


@app.get("/health")
async def health():
    return {"service": "iep4-analytics", "status": "ok", "milestone": "placeholder"}
