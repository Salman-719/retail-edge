from fastapi import FastAPI

from app.api.routers import agent

app = FastAPI(title="IEP6 — Agent")
app.include_router(agent.router)


@app.get("/health")
async def health():
    return {"service": "iep6_agent", "status": "ok"}
