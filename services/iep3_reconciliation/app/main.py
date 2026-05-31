from fastapi import FastAPI

app = FastAPI(title="IEP3 — Reconciliation")


@app.get("/health")
async def health():
    return {"service": "iep3_reconciliation", "status": "ok"}
