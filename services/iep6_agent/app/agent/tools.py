"""Agent tools: curated, parameterized analytics (safe) + a guarded read-only
SQL escape hatch. All run on the read-only DB session.

Schema reference (epoch-ms BIGINT timestamps):
  global_identities(store_id, first_seen_ts, last_seen_ts, state, ...)
  global_tracking_history(store_id, global_id, timestamp_ms, zone_id, ...)
  tracking_history(store_id, camera_id, timestamp_ms, ...)
  zones(id, store_id, name, ...)
"""
import re
import time

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings


def _window_start_ms(window_hours: float) -> int:
    return int((time.time() - window_hours * 3600) * 1000)


async def get_metrics(session: AsyncSession, metric: str, store_id: str,
                      window_hours: float = 24.0) -> dict:
    """Curated analytics. `metric` ∈ footfall | active_visitors | avg_dwell_seconds
    | zone_breakdown | camera_activity."""
    since = _window_start_ms(window_hours)
    p = {"sid": store_id, "since": since}

    if metric == "footfall":
        q = text("SELECT count(*) AS visitors FROM global_identities "
                 "WHERE store_id = :sid AND first_seen_ts >= :since")
    elif metric == "active_visitors":
        q = text("SELECT count(*) AS active FROM global_identities "
                 "WHERE store_id = :sid AND state = 'active'")
    elif metric == "avg_dwell_seconds":
        q = text("SELECT round(avg((last_seen_ts - first_seen_ts)/1000.0)::numeric, 1) "
                 "AS avg_dwell_seconds FROM global_identities "
                 "WHERE store_id = :sid AND first_seen_ts >= :since")
    elif metric == "zone_breakdown":
        q = text("SELECT z.name AS zone, count(DISTINCT g.global_id) AS visitors "
                 "FROM global_tracking_history g LEFT JOIN zones z ON z.id = g.zone_id "
                 "WHERE g.store_id = :sid AND g.timestamp_ms >= :since "
                 "GROUP BY z.name ORDER BY visitors DESC")
    elif metric == "camera_activity":
        q = text("SELECT camera_id, count(*) AS observations FROM tracking_history "
                 "WHERE store_id = :sid AND timestamp_ms >= :since "
                 "GROUP BY camera_id ORDER BY observations DESC")
    else:
        return {"error": f"unknown metric '{metric}'"}

    rows = (await session.execute(q, p)).mappings().all()
    return {"metric": metric, "store_id": store_id, "window_hours": window_hours,
            "rows": [dict(r) for r in rows]}


_FORBIDDEN = re.compile(r"\b(insert|update|delete|drop|alter|truncate|create|grant|"
                        r"revoke|copy|vacuum|merge)\b", re.IGNORECASE)


async def run_readonly_sql(session: AsyncSession, sql: str) -> dict:
    """Guarded escape hatch. Disabled unless ENABLE_RAW_SQL; SELECT-only; the
    DB role is read-only and statement_timeout caps runtime (defense in depth)."""
    if not settings.ENABLE_RAW_SQL:
        return {"error": "raw SQL is disabled; use get_metrics"}
    s = sql.strip().rstrip(";")
    if ";" in s:
        return {"error": "only a single statement is allowed"}
    if not re.match(r"^\s*(select|with)\b", s, re.IGNORECASE) or _FORBIDDEN.search(s):
        return {"error": "only read-only SELECT/WITH queries are allowed"}
    rows = (await session.execute(text(s))).mappings().all()
    return {"rows": [dict(r) for r in rows][:200]}
