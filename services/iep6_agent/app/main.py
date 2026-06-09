from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator

app = FastAPI(title="IEP6 — Agent")
Instrumentator().instrument(app).expose(app)


@app.get("/health")
async def health():
    return {"service": "iep6_agent", "status": "ok"}
