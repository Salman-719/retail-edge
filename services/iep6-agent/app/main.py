from fastapi import FastAPI

app = FastAPI(title="IEP5 — Agent")


@app.get("/health")
async def health():
    return {"service": "iep5-agent", "status": "ok"}
