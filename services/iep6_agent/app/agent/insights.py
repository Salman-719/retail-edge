"""Scheduled insight reports (M2) and proactive alert checks (M3)."""
import json
import logging

from openai import AsyncOpenAI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent import tools
from app.core.config import settings

log = logging.getLogger(__name__)
_client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)


async def _store_ids(session: AsyncSession) -> list[str]:
    rows = (await session.execute(text("SELECT id FROM stores"))).scalars().all()
    return [str(r) for r in rows]


async def generate_insight(
    session: AsyncSession,
    store_id: str,
    *,
    kind: str = "daily_summary",
    window_hours: float = 24.0,
    title: str = "Daily summary",
) -> dict:
    """Summarize a store analytics window and persist it to agent_insights."""
    metrics = {
        m: await tools.get_metrics(session, m, store_id, window_hours)
        for m in ("footfall", "avg_dwell_seconds", "zone_breakdown", "camera_activity")
    }
    period = "weekly" if window_hours >= 168 else "daily"
    resp = await _client.chat.completions.create(
        model=settings.OPENAI_MODEL, max_tokens=settings.OPENAI_MAX_TOKENS,
        messages=[
            {"role": "system", "content": f"Write a brief {period} retail-analytics "
             "summary (footfall, dwell, busiest zones, camera coverage) from the "
             "JSON metrics. 4-6 sentences, quantitative, no preamble."},
            {"role": "user", "content": json.dumps(metrics, default=str)},
        ],
    )
    body = resp.choices[0].message.content or ""
    await session.execute(
        text("INSERT INTO agent_insights (store_id, kind, title, body, metrics) "
             "VALUES (CAST(:sid AS uuid), :kind, :title, :body, CAST(:m AS jsonb))"),
        {"sid": store_id, "kind": kind, "title": title, "body": body,
         "m": json.dumps(metrics, default=str)},
    )
    await session.commit()
    return {"store_id": store_id, "body": body}


async def check_alerts(session: AsyncSession, store_id: str) -> list[dict]:
    """Threshold-based proactive alerts.

    The queue threshold now comes from alert_rules (the queue_buildup type) —
    alert_configs was retired (0018_drop_alert_configs; thresholds moved onto
    alert_rules). Use the tightest (MIN) people_threshold across the store's
    active queue_buildup rules; default 10 when no such rule exists.
    """
    cfg = (await session.execute(
        text("SELECT MIN(people_threshold) AS queue_people_threshold FROM alert_rules "
             "WHERE store_id = CAST(:sid AS uuid) AND type = 'queue_buildup' "
             "AND is_active = TRUE AND people_threshold IS NOT NULL"),
        {"sid": store_id})).mappings().first()
    threshold = (cfg or {}).get("queue_people_threshold") or 10
    active = (await tools.get_metrics(session, "active_visitors", store_id))["rows"]
    count = active[0]["active"] if active else 0
    fired = []
    if count >= threshold:
        # de-dupe: skip if an unresolved overcrowding alert already exists
        exists = (await session.execute(
            text("SELECT 1 FROM agent_alerts WHERE store_id=CAST(:sid AS uuid) AND kind='overcrowding' "
                 "AND resolved_at IS NULL LIMIT 1"), {"sid": store_id})).first()
        if not exists:
            await session.execute(
                text("INSERT INTO agent_alerts (store_id, kind, severity, message, details) "
                     "VALUES (CAST(:sid AS uuid),'overcrowding','warning',:msg, CAST(:d AS jsonb))"),
                {"sid": store_id, "msg": f"{count} active visitors (threshold {threshold})",
                 "d": json.dumps({"active": count, "threshold": threshold})})
            await session.commit()
            fired.append({"store_id": store_id, "kind": "overcrowding", "active": count})
    return fired


async def run_all_insights(session_factory) -> None:
    async with session_factory() as s:
        for sid in await _store_ids(s):
            try:
                await generate_insight(s, sid)
            except Exception:
                log.exception("insight failed store=%s", sid)


async def run_all_weekly_insights(session_factory) -> None:
    async with session_factory() as s:
        for sid in await _store_ids(s):
            try:
                await generate_insight(
                    s,
                    sid,
                    kind="weekly_summary",
                    window_hours=168.0,
                    title="Weekly summary",
                )
            except Exception:
                log.exception("weekly insight failed store=%s", sid)


async def run_all_alerts(session_factory) -> None:
    async with session_factory() as s:
        for sid in await _store_ids(s):
            try:
                await check_alerts(s, sid)
            except Exception:
                log.exception("alert check failed store=%s", sid)
