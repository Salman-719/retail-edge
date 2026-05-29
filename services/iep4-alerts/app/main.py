from fastapi import FastAPI

app = FastAPI(title="IEP3 — Alerts")


@app.get("/health")
async def health():
    return {"service": "iep3-alerts", "status": "ok"}
