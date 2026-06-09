"""Camera schedule evaluator — runs every WINDOW_SECONDS via APScheduler.

Evaluates all active camera_schedules against the current local time in each
store's timezone. Calls _on_camera_start / _on_camera_stop when the running
state changes. Camera start/stop is delegated to orchestrator (gRPC to Edge Agent).
"""
import logging
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import text

from app.core.database import AsyncSessionLocal
from app.core import orchestrator
from app.grpc_server import camera_status as _camera_status
from app.metrics import EEP_ACTIVE_CAMERAS, EEP_SCHEDULER_TICKS

log = logging.getLogger(__name__)

# In-memory set of currently-running (store_id, camera_config_id) pairs.
# Rebuilt on EEP startup from Redis-backed camera_status via rebuild_running_cameras().
_running_cameras: set[tuple[str, str]] = set()


def mark_running(store_id: str, camera_config_id: str) -> None:
    _running_cameras.add((str(store_id), str(camera_config_id)))
    EEP_ACTIVE_CAMERAS.set(len(_running_cameras))


def mark_stopped(store_id: str, camera_config_id: str) -> None:
    _running_cameras.discard((str(store_id), str(camera_config_id)))
    EEP_ACTIVE_CAMERAS.set(len(_running_cameras))

_LOAD_SQL = text("""
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
    """Populate _running_cameras from Redis-backed camera_status at EEP startup.

    IEP2 pods survive an EEP restart (k3s keeps them running). Without this,
    the first scheduler tick would send unnecessary StartCamera commands for
    cameras that are already running. We check camera_status (rebuilt from
    Redis in rebuild_running_cameras_on_startup) to avoid redundant commands.

    Must be called AFTER rebuild_running_cameras_on_startup().
    """
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(_LOAD_SQL)
            rows = [dict(r._mapping) for r in result]
    except Exception:
        log.exception("rebuild_running_cameras: DB load failed, skipping")
        return

    now_utc = datetime.now(timezone.utc)

    for row in rows:
        try:
            tz_str = row["store_timezone"] or "UTC"
            try:
                store_tz = ZoneInfo(tz_str)
            except ZoneInfoNotFoundError:
                log.error(
                    "rebuild_running_cameras: invalid timezone %r for store %s — skipping",
                    tz_str, row["store_id"],
                )
                continue

            now_local = now_utc.astimezone(store_tz)
            if not _should_run(row, now_local):
                continue

            store_id  = str(row["store_id"])
            phys_id   = str(row["physical_camera_id"])
            if _camera_status.is_running(store_id, phys_id):
                key = (store_id, str(row["camera_config_id"]))
                _running_cameras.add(key)
                log.info(
                    "rebuild_running_cameras: pre-marked running  store=%s  config=%s",
                    store_id, row["camera_config_id"],
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
            stop_reason="schedule",
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


async def _activate_pending_versions(now_utc: datetime) -> None:
    """Fire any pending_activation versions whose activate_at has passed."""
    try:
        async with AsyncSessionLocal() as db:
            rows_result = await db.execute(
                text("""
                    SELECT scv.id        AS version_id,
                           scv.store_id,
                           prev.id       AS old_version_id
                    FROM store_config_versions scv
                    LEFT JOIN store_config_versions prev
                           ON prev.store_id = scv.store_id
                          AND prev.status   = 'active'
                    WHERE scv.status     = 'pending_activation'
                      AND scv.activate_at <= :now
                """),
                {"now": now_utc},
            )
            pending = rows_result.fetchall()
    except Exception:
        log.exception("_activate_pending_versions: DB query failed, skipping")
        return

    for row in pending:
        try:
            started, stopped = await orchestrator.activate_version_now(
                store_id=str(row.store_id),
                new_version_id=str(row.version_id),
                old_version_id=str(row.old_version_id) if row.old_version_id else None,
            )
            for cc_id in stopped:
                mark_stopped(str(row.store_id), cc_id)
            for cc_id in started:
                mark_running(str(row.store_id), cc_id)
            log.info(
                "Scheduled activation executed  version=%s  started=%d  stopped=%d",
                row.version_id, len(started), len(stopped),
            )
        except Exception:
            log.exception(
                "Pending activation failed for version %s", row.version_id
            )


async def evaluate_schedules() -> None:
    """APScheduler job: evaluate all active schedules and emit start/stop events."""
    tick_start = time.monotonic()

    try:
        async with AsyncSessionLocal() as session:
            rows = await _load_schedules(session)
    except Exception:
        log.exception("evaluate_schedules: DB load failed, skipping tick")
        return

    now_utc = datetime.now(timezone.utc)

    for row in rows:
        try:
            tz_str = row["store_timezone"] or "UTC"
            try:
                now_local = now_utc.astimezone(ZoneInfo(tz_str))
            except ZoneInfoNotFoundError:
                log.error(
                    "evaluate_schedules: invalid timezone %r for store %s — skipping",
                    tz_str, row["store_id"],
                )
                continue

            should_run = _should_run(row, now_local)
            key = (str(row["store_id"]), str(row["camera_config_id"]))

            if should_run and key not in _running_cameras:
                # Don't race with k3s/Docker on-failure restart recovery
                phys_id = str(row.get("physical_camera_id", ""))
                if phys_id:
                    cs = _camera_status.get(str(row["store_id"]), phys_id)
                    if cs and cs["status"] in ("restarting", "starting", "pending"):
                        log.info(
                            "camera %s status=%s — skipping start  config=%s",
                            phys_id, cs["status"], row["camera_config_id"],
                        )
                        continue
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

    await _activate_pending_versions(now_utc)

    elapsed = time.monotonic() - tick_start
    from app.core.scheduler import _WINDOW_SECONDS
    if elapsed > _WINDOW_SECONDS * 0.5:
        log.warning(
            "evaluate_schedules took %.1fs — approaching %.0fs interval",
            elapsed, _WINDOW_SECONDS,
        )

    EEP_SCHEDULER_TICKS.inc()
