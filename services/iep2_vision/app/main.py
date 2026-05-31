from fastapi import FastAPI

app = FastAPI(title="IEP2 — Vision")


@app.get("/health")
async def health():
    return {"service": "iep2_vision", "status": "ok"}
