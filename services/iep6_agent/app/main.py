from fastapi import FastAPI

app = FastAPI(title="IEP6 — Agent")


@app.get("/health")
async def health():
    return {"service": "iep6_agent", "status": "ok"}
