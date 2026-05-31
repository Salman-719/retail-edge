from fastapi import FastAPI

app = FastAPI(title="IEP1 — Ingestion")


@app.get("/health")
async def health():
    return {"service": "iep1_ingestion", "status": "ok"}
