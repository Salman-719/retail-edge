from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator

app = FastAPI(title="IEP5 — Analytics")
Instrumentator().instrument(app).expose(app)


@app.get("/health")
async def health():
    return {"service": "iep5_analytics", "status": "ok"}
