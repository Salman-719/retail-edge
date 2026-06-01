"""Camera schedule evaluator — runs every 60 s via APScheduler.

Evaluates all active camera_schedules against the current local time in each
store's timezone. Calls _on_camera_start / _on_camera_stop stubs when the
running state changes. Phase 7 replaces the stubs with Docker SDK calls.
"""
import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import text

from app.core.database import AsyncSessionLocal

log = logging.getLogger(__name__)

# In-memory set of currently-running (store_id, camera_config_id) pairs.
# Resets on EEP restart. Phase 7 will replace this with a DB/Docker status query.
_running_cameras: set[tuple[str, str]] = set()

_LOAD_SQL = text("""
SELECT
    cs.id              AS schedule_id,
    cs.store_id,
    cs.camera_config_id,
    cs.days_of_week,
    cs.start_time,
    cs.end_time,
    s.timezone         AS store_timezone
FROM camera_schedules cs
JOIN stores s ON s.id = cs.store_id
WHERE cs.is_active = true
  AND s.status = 'active'
""")


async def _load_schedules(session) -> list[dict]:
    result = await session.execute(_LOAD_SQL)
    return [dict(row._mapping) for row in result]


def _should_run(row: dict, now_local: datetime) -> bool:
    current_day  = now_local.weekday()
    current_time = now_local.time().replace(tzinfo=None)
    return (
        current_day in row["days_of_week"]
        and row["start_time"] <= current_time < row["end_time"]
    )


async def _on_camera_start(row: dict) -> None:
    log.info(
        "SCHEDULE: start camera",
        extra={
            "store_id":         str(row["store_id"]),
            "camera_config_id": str(row["camera_config_id"]),
        },
    )
    # Phase 7: call Docker SDK to start IEP2 container
    # Phase 7: push StartCamera command to edge agent for IEP1


async def _on_camera_stop(row: dict) -> None:
    log.info(
        "SCHEDULE: stop camera",
        extra={
            "store_id":         str(row["store_id"]),
            "camera_config_id": str(row["camera_config_id"]),
        },
    )
    # Phase 7: call Docker SDK to stop IEP2 container
    # Phase 7: push StopCamera command to edge agent for IEP1


async def evaluate_schedules() -> None:
    """APScheduler job: evaluate all active schedules and emit start/stop events."""
    try:
        async with AsyncSessionLocal() as session:
            rows = await _load_schedules(session)
    except Exception:
        log.exception("evaluate_schedules: DB load failed, skipping tick")
        return

    now_utc = datetime.now(timezone.utc)

    for row in rows:
        try:
            store_tz  = ZoneInfo(row["store_timezone"] or "UTC")
            now_local = now_utc.astimezone(store_tz)
            should_run = _should_run(row, now_local)
            key = (str(row["store_id"]), str(row["camera_config_id"]))

            if should_run and key not in _running_cameras:
                await _on_camera_start(row)
                _running_cameras.add(key)

            elif not should_run and key in _running_cameras:
                await _on_camera_stop(row)
                _running_cameras.discard(key)

        except Exception:
            log.exception(
                "evaluate_schedules: error processing schedule_id=%s",
                row.get("schedule_id"),
            )
