"""IEP6 agent HTTP API. Matches the frontend contract (slug-based):
  POST /api/store/{slug}/agent/chat     {message, conversation_id} -> {message, chart?}
  GET  /api/store/{slug}/agent/reports?type=daily|weekly
Plus ops/test endpoints under /api/agent. Routed to this service by the frontend
nginx (/api/store/*/agent and /api/agent -> iep6)."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.runtime import answer
from app.core.database import get_session

router = APIRouter(prefix="/api", tags=["agent"])


async def _store_id_for_slug(slug: str, session: AsyncSession) -> str:
    row = (await session.execute(
        text("SELECT id FROM stores WHERE slug = :slug"), {"slug": slug})).first()
    if not row:
        raise HTTPException(status_code=404, detail=f"store '{slug}' not found")
    return str(row[0])


class ChatIn(BaseModel):
    message: str
    conversation_id: str | None = None


# ── Frontend contract (slug-based) ──────────────────────────────────────────
@router.post("/store/{slug}/agent/chat")
async def chat(slug: str, body: ChatIn,
               session: AsyncSession = Depends(get_session)) -> dict:
    store_id = await _store_id_for_slug(slug, session)
    result = await answer(body.message, store_id, session)
    return {"message": result.get("answer", ""), "chart": None,
            "conversation_id": body.conversation_id}


@router.get("/store/{slug}/agent/reports")
async def reports(slug: str, type: str = "daily",
                  session: AsyncSession = Depends(get_session)) -> dict:
    store_id = await _store_id_for_slug(slug, session)
    rows = (await session.execute(
        text("SELECT title, body, created_at FROM agent_insights "
             "WHERE store_id = CAST(:sid AS uuid) ORDER BY created_at DESC LIMIT 10"),
        {"sid": store_id})).mappings().all()
    return {"type": type, "reports": [dict(r) for r in rows]}


# ── Ops / direct test endpoints ─────────────────────────────────────────────
class QueryIn(BaseModel):
    store_id: str
    question: str


@router.post("/agent/query")
async def query(body: QueryIn, session: AsyncSession = Depends(get_session)) -> dict:
    return await answer(body.question, body.store_id, session)


@router.get("/agent/insights")
async def insights(store_id: str, limit: int = 5,
                   session: AsyncSession = Depends(get_session)) -> dict:
    rows = (await session.execute(
        text("SELECT kind, title, body, created_at FROM agent_insights "
             "WHERE store_id = CAST(:sid AS uuid) ORDER BY created_at DESC LIMIT :lim"),
        {"sid": store_id, "lim": limit})).mappings().all()
    return {"store_id": store_id, "insights": [dict(r) for r in rows]}


@router.get("/agent/alerts")
async def alerts(store_id: str, unresolved_only: bool = True,
                 session: AsyncSession = Depends(get_session)) -> dict:
    sql = ("SELECT kind, severity, message, details, created_at, resolved_at "
           "FROM agent_alerts WHERE store_id = CAST(:sid AS uuid)")
    if unresolved_only:
        sql += " AND resolved_at IS NULL"
    sql += " ORDER BY created_at DESC LIMIT 50"
    rows = (await session.execute(text(sql), {"sid": store_id})).mappings().all()
    return {"store_id": store_id, "alerts": [dict(r) for r in rows]}
