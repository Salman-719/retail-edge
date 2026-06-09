from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator

app = FastAPI(title="IEP4 — Alerts")
Instrumentator().instrument(app).expose(app)


@app.get("/health")
async def health():
    return {"service": "iep4_alerts", "status": "ok"}
