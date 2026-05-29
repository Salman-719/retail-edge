from fastapi import FastAPI

app = FastAPI(title="IEP5 — Analytics")


@app.get("/health")
async def health():
    return {"service": "iep5-analytics", "status": "ok"}
