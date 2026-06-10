"""IEP6 agent HTTP API. Matches the frontend contract (slug-based):
  POST /api/store/{slug}/agent/chat     {message, conversation_id} -> {message, chart?}
  GET  /api/store/{slug}/agent/reports?type=daily|weekly
Plus ops/test endpoints under /api/agent. Routed to this service by the frontend
nginx (/api/store/*/agent and /api/agent -> iep6)."""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.runtime import answer
from app.core.auth import (
    authorize_store_id,
    authorize_store_slug,
    get_current_user_payload,
)
from app.core.database import get_session

router = APIRouter(prefix="/api", tags=["agent"])


class ChatIn(BaseModel):
    message: str
    conversation_id: str | None = None


# ── Frontend contract (slug-based) ──────────────────────────────────────────
@router.post("/store/{slug}/agent/chat")
async def chat(slug: str, body: ChatIn,
               session: AsyncSession = Depends(get_session),
               payload: dict = Depends(get_current_user_payload)) -> dict:
    store_id = await authorize_store_slug(slug, payload, session)
    result = await answer(body.message, store_id, session)
    return {"message": result.get("answer", ""), "chart": None,
            "conversation_id": body.conversation_id}


@router.get("/store/{slug}/agent/reports")
async def reports(slug: str, type: str = "daily",
                  session: AsyncSession = Depends(get_session),
                  payload: dict = Depends(get_current_user_payload)) -> dict:
    store_id = await authorize_store_slug(slug, payload, session)
    kind = "weekly_summary" if type == "weekly" else "daily_summary"
    rows = (await session.execute(
        text("SELECT id, title, body, created_at FROM agent_insights "
             "WHERE store_id = CAST(:sid AS uuid) AND kind = :kind "
             "ORDER BY created_at DESC LIMIT 10"),
        {"sid": store_id, "kind": kind})).mappings().all()
    return {"type": type, "reports": [dict(r) for r in rows]}


# ── Ops / direct test endpoints ─────────────────────────────────────────────
class QueryIn(BaseModel):
    store_id: str
    question: str


@router.post("/agent/query")
async def query(body: QueryIn, session: AsyncSession = Depends(get_session),
                payload: dict = Depends(get_current_user_payload)) -> dict:
    store_id = await authorize_store_id(body.store_id, payload, session)
    return await answer(body.question, store_id, session)


@router.get("/agent/insights")
async def insights(store_id: str, limit: int = 5,
                   session: AsyncSession = Depends(get_session),
                   payload: dict = Depends(get_current_user_payload)) -> dict:
    store_id = await authorize_store_id(store_id, payload, session)
    rows = (await session.execute(
        text("SELECT kind, title, body, created_at FROM agent_insights "
             "WHERE store_id = CAST(:sid AS uuid) ORDER BY created_at DESC LIMIT :lim"),
        {"sid": store_id, "lim": limit})).mappings().all()
    return {"store_id": store_id, "insights": [dict(r) for r in rows]}


@router.get("/agent/alerts")
async def alerts(store_id: str, unresolved_only: bool = True,
                 session: AsyncSession = Depends(get_session),
                 payload: dict = Depends(get_current_user_payload)) -> dict:
    store_id = await authorize_store_id(store_id, payload, session)
    sql = ("SELECT kind, severity, message, details, created_at, resolved_at "
           "FROM agent_alerts WHERE store_id = CAST(:sid AS uuid)")
    if unresolved_only:
        sql += " AND resolved_at IS NULL"
    sql += " ORDER BY created_at DESC LIMIT 50"
    rows = (await session.execute(text(sql), {"sid": store_id})).mappings().all()
    return {"store_id": store_id, "alerts": [dict(r) for r in rows]}
