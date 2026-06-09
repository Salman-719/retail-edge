"""Store-hours camera evaluator — runs every WINDOW_SECONDS via APScheduler (C2).

Evaluates each active store's store_operating_hours against the current local
time in the store's timezone: when the store is open, every camera_config of its
ACTIVE config version is started; when closed, they are stopped. Calls
_on_camera_start / _on_camera_stop on running-state transitions. Camera start/stop
is delegated to orchestrator (gRPC to Edge Agent). Store open/close drives the
IEP5 shift boundary via the per-store running-set transitions below.
"""
import asyncio
import logging
import time
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import text

from app.core.database import AsyncSessionLocal
from app.core import orchestrator
from app.grpc_server import camera_status as _camera_status

log = logging.getLogger(__name__)

# In-memory set of currently-running (store_id, camera_config_id) pairs.
# Rebuilt on EEP startup from Redis-backed camera_status via rebuild_running_cameras().
_running_cameras: set[tuple[str, str]] = set()

# Per-store shift START date (store-local), recorded when a store's first camera
# starts. Used as the shift_date when the store's last camera stops (end of
# shift), so shifts spanning midnight keep their start date (SPEC-004).
_store_shift_start: dict[str, date] = {}


def _stores_running() -> set[str]:
    return {sid for (sid, _cfg) in _running_cameras}


def _fire_shift_end(store_id: str, shift_date: date) -> None:
    """Run the end-of-shift closing + IEP5 launch as a background task so the
    scheduler tick is never blocked by the closing transaction's retry waits."""
    from app.core import shift_closer

    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)

    async def _run() -> None:
        try:
            await shift_closer.close_shift_and_run_iep5(store_id, shift_date, now_ms)
        except Exception:
            log.exception("shift-end handler failed for store=%s", store_id)

    log.info("SCHEDULE: shift end detected — store=%s shift_date=%s", store_id, shift_date)
    asyncio.create_task(_run())


def mark_running(store_id: str, camera_config_id: str) -> None:
    _running_cameras.add((str(store_id), str(camera_config_id)))


def mark_stopped(store_id: str, camera_config_id: str) -> None:
    _running_cameras.discard((str(store_id), str(camera_config_id)))

# Per-weekday open/close for every active store.
_HOURS_SQL = text("""
SELECT soh.store_id,
       soh.day_of_week,
       soh.is_open,
       soh.open_time,
       soh.close_time,
       s.timezone        AS store_timezone
FROM store_operating_hours soh
JOIN stores s ON s.id = soh.store_id
WHERE s.status = 'active'
""")

# Every camera_config of each active store's ACTIVE config version.
_ACTIVE_CAMERAS_SQL = text("""
SELECT cc.store_id,
       cc.id              AS camera_config_id,
       pc.id              AS physical_camera_id,
       s.timezone         AS store_timezone
FROM camera_configs cc
JOIN store_config_versions scv ON scv.id = cc.version_id
JOIN stores s                  ON s.id  = cc.store_id
JOIN physical_cameras pc       ON pc.id = cc.physical_camera_id
WHERE scv.status = 'active'
  AND s.status   = 'active'
""")


async def _load_store_hours(session) -> tuple[dict, dict, list]:
    """Load (hours_by_store, store_tz, cameras) for one evaluation tick.

    hours_by_store: store_id(str) -> {day_of_week(int) -> row dict}
    store_tz:       store_id(str) -> tz string
    cameras:        list of active-version camera_config row dicts
    """
    hours_res = await session.execute(_HOURS_SQL)
    hours_by_store: dict[str, dict[int, dict]] = {}
    store_tz: dict[str, str] = {}
    for r in hours_res:
        m = dict(r._mapping)
        sid = str(m["store_id"])
        hours_by_store.setdefault(sid, {})[int(m["day_of_week"])] = m
        store_tz[sid] = m["store_timezone"] or "UTC"

    cam_res = await session.execute(_ACTIVE_CAMERAS_SQL)
    cameras = [dict(r._mapping) for r in cam_res]
    for c in cameras:
        store_tz.setdefault(str(c["store_id"]), c["store_timezone"] or "UTC")

    return hours_by_store, store_tz, cameras


def _store_open(hours_by_day: dict[int, dict], now_local: datetime) -> bool:
    """True if the store is open at now_local, honoring overnight wrap.

    For the current weekday's row: if close > open it is a same-day window
    (open <= now < close); if close <= open it wraps past midnight
    (now >= open OR now < close). The previous day's row is also consulted so an
    overnight window opened yesterday still counts in today's early hours even if
    today itself is closed. is_open=false / missing row → closed.
    """
    t = now_local.time().replace(tzinfo=None)
    today = now_local.weekday()

    row = hours_by_day.get(today)
    if row and row["is_open"] and row["open_time"] is not None and row["close_time"] is not None:
        o, c = row["open_time"], row["close_time"]
        if c > o:
            if o <= t < c:
                return True
        else:  # overnight wrap
            if t >= o or t < c:
                return True

    prev = hours_by_day.get((today - 1) % 7)
    if prev and prev["is_open"] and prev["open_time"] is not None and prev["close_time"] is not None:
        o, c = prev["open_time"], prev["close_time"]
        if c <= o and t < c:  # yesterday's window wrapped into today
            return True

    return False


def _store_open_now(sid: str, hours_by_store: dict, store_tz: dict, now_utc: datetime) -> bool:
    """Resolve store-openness for a tick, converting now_utc into store-local."""
    tz_str = store_tz.get(sid, "UTC")
    try:
        now_local = now_utc.astimezone(ZoneInfo(tz_str))
    except ZoneInfoNotFoundError:
        log.error(
            "evaluate_store_hours: invalid timezone %r for store %s — treating as closed",
            tz_str, sid,
        )
        return False
    return _store_open(hours_by_store.get(sid, {}), now_local)


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
            hours_by_store, store_tz, cameras = await _load_store_hours(session)
    except Exception:
        log.exception("rebuild_running_cameras: DB load failed, skipping")
        return

    now_utc = datetime.now(timezone.utc)
    open_cache: dict[str, bool] = {}

    for row in cameras:
        try:
            store_id = str(row["store_id"])
            if store_id not in open_cache:
                open_cache[store_id] = _store_open_now(store_id, hours_by_store, store_tz, now_utc)
            if not open_cache[store_id]:
                continue

            phys_id = str(row["physical_camera_id"])
            if _camera_status.is_running(store_id, phys_id):
                key = (store_id, str(row["camera_config_id"]))
                _running_cameras.add(key)
                log.info(
                    "rebuild_running_cameras: pre-marked running  store=%s  config=%s",
                    store_id, row["camera_config_id"],
                )
        except Exception:
            log.exception(
                "rebuild_running_cameras: error for camera_config_id=%s",
                row.get("camera_config_id"),
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


async def evaluate_store_hours() -> None:
    """APScheduler job: open store → start its active-version cameras; closed → stop."""
    tick_start = time.monotonic()

    try:
        async with AsyncSessionLocal() as session:
            hours_by_store, store_tz, cameras = await _load_store_hours(session)
    except Exception:
        log.exception("evaluate_store_hours: DB load failed, skipping tick")
        return

    now_utc = datetime.now(timezone.utc)
    stores_before = _stores_running()

    # Resolve each store's openness once per tick.
    open_cache: dict[str, bool] = {}

    def _is_open(sid: str) -> bool:
        if sid not in open_cache:
            open_cache[sid] = _store_open_now(sid, hours_by_store, store_tz, now_utc)
        return open_cache[sid]

    for row in cameras:
        try:
            store_id = str(row["store_id"])
            should_run = _is_open(store_id)
            key = (store_id, str(row["camera_config_id"]))

            if should_run and key not in _running_cameras:
                # Don't race with k3s/Docker on-failure restart recovery
                phys_id = str(row.get("physical_camera_id", ""))
                if phys_id:
                    cs = _camera_status.get(store_id, phys_id)
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
                "evaluate_store_hours: error processing camera_config_id=%s",
                row.get("camera_config_id"),
            )

    # ── Per-store shift start/end detection ──────────────────────────────────
    stores_after = _stores_running()

    def _local_today(sid: str) -> date:
        try:
            return now_utc.astimezone(ZoneInfo(store_tz.get(sid, "UTC"))).date()
        except Exception:
            return now_utc.date()

    for sid in stores_after - stores_before:        # 0 -> >0 : shift start
        _store_shift_start.setdefault(sid, _local_today(sid))

    for sid in stores_before - stores_after:        # >0 -> 0 : shift end
        shift_date = _store_shift_start.pop(sid, _local_today(sid))
        _fire_shift_end(sid, shift_date)

    await _activate_pending_versions(now_utc)

    elapsed = time.monotonic() - tick_start
    from app.core.scheduler import _WINDOW_SECONDS
    if elapsed > _WINDOW_SECONDS * 0.5:
        log.warning(
            "evaluate_store_hours took %.1fs — approaching %.0fs interval",
            elapsed, _WINDOW_SECONDS,
        )
