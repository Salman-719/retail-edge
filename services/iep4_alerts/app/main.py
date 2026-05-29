from fastapi import FastAPI

app = FastAPI(title="IEP4 — Alerts")


@app.get("/health")
async def health():
    return {"service": "iep4-alerts", "status": "ok"}
