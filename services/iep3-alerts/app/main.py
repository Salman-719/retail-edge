"""IEP3 — Alerts & Rule Engine (Milestone 3+)."""
from fastapi import FastAPI

app = FastAPI(
    title="RetailVision IEP3 — Alerts",
    version="0.1.0",
    description="Evaluates rule conditions on tracking events and emits alerts. Placeholder — active in Milestone 3.",
)


@app.get("/health")
async def health():
    return {"service": "iep3-alerts", "status": "ok", "milestone": "placeholder"}
