"""IEP5 — AI Agent (LLM-powered retail insights).

Natural language interface for querying retail analytics.
Stub endpoints — logic will be implemented in Milestone 3.
"""
import uuid
from datetime import datetime
from typing import List

from fastapi import FastAPI

from app.schemas import (
    AgentQuery, AgentResponse,
    ReportRequest, ReportResponse,
    Suggestion,
    HealthResponse,
)

app = FastAPI(
    title="RetailVision IEP5 — AI Agent",
    version="0.1.0",
    description="LLM-powered natural language interface for querying retail analytics.",
)


# ── Health ───────────────────────────────────────────────────────────────────

@app.get("/health", response_model=HealthResponse)
async def health():
    return HealthResponse()


# ── Query ────────────────────────────────────────────────────────────────────

@app.post("/agent/query", response_model=AgentResponse)
async def query(payload: AgentQuery):
    """Answer a natural-language question about retail data.
    Stub — returns placeholder until LLM integration is implemented."""
    return AgentResponse(
        answer="Agent not yet implemented. This is a placeholder response.",
        confidence=0.0,
        sources=[],
    )


# ── Reports ──────────────────────────────────────────────────────────────────

@app.post("/agent/report", response_model=ReportResponse)
async def generate_report(payload: ReportRequest):
    """Generate an automated report.
    Stub — returns placeholder markdown."""
    return ReportResponse(
        report_id=uuid.uuid4().hex,
        store_id=payload.store_id,
        report_type=payload.report_type,
        markdown=f"# {payload.report_type} Report\n\nNo data available yet.",
        generated_at=datetime.utcnow(),
    )


# ── Suggestions ──────────────────────────────────────────────────────────────

@app.get("/agent/suggestions/{store_id}", response_model=List[Suggestion])
async def suggestions(store_id: str):
    """Return proactive insights for a store.
    Stub — returns empty list."""
    return []
