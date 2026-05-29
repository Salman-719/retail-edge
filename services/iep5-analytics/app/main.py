from fastapi import FastAPI

app = FastAPI(title="IEP4 — Analytics")


@app.get("/health")
async def health():
    return {"service": "iep4-analytics", "status": "ok"}
