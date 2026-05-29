from fastapi import FastAPI

app = FastAPI(title="IEP1 — Ingestion")


@app.get("/health")
async def health():
    return {"service": "iep1-ingestion", "status": "ok"}
