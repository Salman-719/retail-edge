"""IEP6 agent HTTP API. Exposed at /api/agent/* (routed to this service by the
ingress; the SPA proxies /api)."""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.runtime import answer
from app.core.database import get_session

router = APIRouter(prefix="/api/agent", tags=["agent"])


class QueryIn(BaseModel):
    store_id: str
    question: str


@router.post("/query")
async def query(body: QueryIn, session: AsyncSession = Depends(get_session)) -> dict:
    """Natural-language Q&A grounded in the store's analytics data."""
    return await answer(body.question, body.store_id, session)
