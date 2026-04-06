"""IEP2 — Vision Processing (YOLO + ByteTrack) (Milestone 3+)."""
from fastapi import FastAPI

app = FastAPI(
    title="RetailVision IEP2 — Vision",
    version="0.1.0",
    description="Runs YOLO+ByteTrack inference on video chunks and emits tracking events. Placeholder — active in Milestone 3.",
)


@app.get("/health")
async def health():
    return {"service": "iep2-vision", "status": "ok", "milestone": "placeholder"}
