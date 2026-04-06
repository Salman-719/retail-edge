"""IEP5 — AI Agent (LLM-powered retail insights) (Milestone 3+)."""
from fastapi import FastAPI

app = FastAPI(
    title="RetailVision IEP5 — AI Agent",
    version="0.1.0",
    description="LLM-powered natural language interface for querying retail analytics. Placeholder — active in Milestone 3.",
)


@app.get("/health")
async def health():
    return {"service": "iep5-agent", "status": "ok", "milestone": "placeholder"}
