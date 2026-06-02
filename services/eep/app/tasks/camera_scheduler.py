"""Camera schedule evaluator — runs every 60 s via APScheduler.

Evaluates all active camera_schedules against the current local time in each
store's timezone. Calls _on_camera_start / _on_camera_stop stubs when the
running state changes. Phase 7 replaces the stubs with Docker SDK calls.
"""
import asyncio
import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import text

from app.core.database import AsyncSessionLocal
from app.core import iep2_docker, orchestrator

log = logging.getLogger(__name__)

# In-memory set of currently-running (store_id, camera_config_id) pairs.
# Resets on EEP restart. Phase 7 will replace this with a DB/Docker status query.
_running_cameras: set[tuple[str, str]] = set()


def mark_running(store_id: str, camera_config_id: str) -> None:
    _running_cameras.add((str(store_id), str(camera_config_id)))


def mark_stopped(store_id: str, camera_config_id: str) -> None:
    _running_cameras.discard((str(store_id), str(camera_config_id)))

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

# Extends _LOAD_SQL with physical_camera_id — used only at startup for Docker state rebuild.
_REBUILD_SQL = text("""
SELECT
    cs.id              AS schedule_id,
    cs.store_id,
    cs.camera_config_id,
    cs.days_of_week,
    cs.start_time,
    cs.end_time,
    s.timezone         AS store_timezone,
    pc.id              AS physical_camera_id
FROM camera_schedules cs
JOIN stores s                  ON s.id   = cs.store_id
JOIN camera_configs cc         ON cc.id  = cs.camera_config_id
JOIN store_config_versions scv ON scv.id = cc.version_id
JOIN physical_cameras pc       ON pc.id  = cc.physical_camera_id
WHERE cs.is_active = true
  AND s.status = 'active'
""")


async def rebuild_running_cameras() -> None:
    """Populate _running_cameras from live Docker state at EEP startup.

    IEP2 containers survive an EEP restart (they are detached Docker containers).
    Without this, the first scheduler tick after restart would force-remove and
    recreate every running IEP2 container — killing ByteTrack and ReID state
    mid-session. We query Docker for each schedule that should currently be
    running and pre-mark it so evaluate_schedules skips the unnecessary restart.
    """
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(_REBUILD_SQL)
            rows = [dict(r._mapping) for r in result]
    except Exception:
        log.exception("rebuild_running_cameras: DB load failed, skipping")
        return

    now_utc = datetime.now(timezone.utc)
    loop = asyncio.get_running_loop()

    for row in rows:
        try:
            store_tz  = ZoneInfo(row["store_timezone"] or "UTC")
            now_local = now_utc.astimezone(store_tz)
            if not _should_run(row, now_local):
                continue

            status = await loop.run_in_executor(
                None,
                iep2_docker.get_iep2_status,
                str(row["store_id"]),
                str(row["physical_camera_id"]),
            )
            if status == "running":
                key = (str(row["store_id"]), str(row["camera_config_id"]))
                _running_cameras.add(key)
                log.info(
                    "rebuild_running_cameras: IEP2 already running, pre-marked",
                    extra={
                        "store_id":         str(row["store_id"]),
                        "camera_config_id": str(row["camera_config_id"]),
                    },
                )
        except Exception:
            log.exception(
                "rebuild_running_cameras: error for schedule_id=%s",
                row.get("schedule_id"),
            )


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
    try:
        await orchestrator.start_camera_workers(
            store_id=str(row["store_id"]),
            camera_config_id=str(row["camera_config_id"]),
        )
    except Exception as exc:
        log.error(
            "Failed to start camera workers",
            exc_info=exc,
            extra={
                "store_id":         str(row["store_id"]),
                "camera_config_id": str(row["camera_config_id"]),
            },
        )


async def _on_camera_stop(row: dict) -> None:
    log.info(
        "SCHEDULE: stop camera",
        extra={
            "store_id":         str(row["store_id"]),
            "camera_config_id": str(row["camera_config_id"]),
        },
    )
    try:
        await orchestrator.stop_camera_workers(
            store_id=str(row["store_id"]),
            camera_config_id=str(row["camera_config_id"]),
        )
    except Exception as exc:
        log.error(
            "Failed to stop camera workers",
            exc_info=exc,
            extra={
                "store_id":         str(row["store_id"]),
                "camera_config_id": str(row["camera_config_id"]),
            },
        )


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
