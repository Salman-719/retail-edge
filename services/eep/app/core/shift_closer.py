"""End-of-shift closing sequence (owned by EEP), then launch the IEP5 job.

Steps:
  1. Idempotency guard — skip if analytics.daily_store_summary already has this
     (store, shift_date).
  2. StopCamera for the store's open camera sessions (production only; the dev
     pipeline owns camera lifecycle in DEBUG_MODE).
  3. Closing transaction (one tx, retried 5/15/45 s): close open visit_sessions,
     flush open active_person_state zone sessions to zone_transition_log, delete
     active_person_state. On total failure: send a failure email and DO NOT
     launch the job.
  4. Launch the IEP5 analytics job (it re-checks preflight + idempotency itself).
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date

from sqlalchemy import text

from app.core import email, iep5_manager, orchestrator
from app.core.config import settings
from app.core.database import AsyncSessionLocal

log = logging.getLogger(__name__)

_RETRY_DELAYS = (0, 5, 15, 45)  # initial attempt + 3 retries

_CLOSE_VISITS = text("""
    UPDATE visit_sessions
    SET exited_at_ms = :end_ms
    WHERE store_id = :sid AND exited_at_ms IS NULL
""")

# GREATEST guards the zone_transition_log positive_dwell CHECK (exited > entered).
_FLUSH_ZONES = text("""
    INSERT INTO zone_transition_log (
        global_id, store_id, zone_id, entered_at_ms, exited_at_ms,
        is_employee, entry_batch, exit_batch
    )
    SELECT global_id, store_id, current_zone_id,
           entered_current_zone_at,
           GREATEST(:end_ms, entered_current_zone_at + 1),
           is_employee, last_batch_number, last_batch_number
    FROM active_person_state
    WHERE store_id = :sid
      AND current_zone_id IS NOT NULL
      AND entered_current_zone_at IS NOT NULL
""")

_DELETE_APS = text("DELETE FROM active_person_state WHERE store_id = :sid")

_SUMMARY_EXISTS = text("""
    SELECT 1 FROM analytics.daily_store_summary
    WHERE store_id = :sid AND date = :d LIMIT 1
""")

_OPEN_SESSIONS = text("""
    SELECT physical_camera_id, camera_config_id
    FROM camera_runtime_sessions
    WHERE store_id = :sid AND stopped_at IS NULL
      AND physical_camera_id IS NOT NULL AND camera_config_id IS NOT NULL
""")


async def close_shift_and_run_iep5(store_id: str, shift_date: date, shift_end_ms: int) -> None:
    import uuid as _uuid
    sid = _uuid.UUID(store_id)

    # ── 1. Idempotency guard ─────────────────────────────────────────────────
    async with AsyncSessionLocal() as db:
        already = await db.execute(_SUMMARY_EXISTS, {"sid": sid, "d": shift_date})
        if already.first() is not None:
            log.info("shift_closer: analytics already exist for store=%s date=%s — skipping",
                     store_id, shift_date)
            return

    # ── 2. StopCamera (production only) ──────────────────────────────────────
    if not settings.DEBUG_MODE:
        try:
            async with AsyncSessionLocal() as db:
                rows = (await db.execute(_OPEN_SESSIONS, {"sid": sid})).fetchall()
            for _phys, cfg in rows:
                await orchestrator.stop_camera_workers(
                    store_id=store_id, camera_config_id=str(cfg), stop_reason="schedule",
                )
        except Exception:
            log.exception("shift_closer: StopCamera step failed (continuing) store=%s", store_id)

    # ── 3. Closing transaction with retries ──────────────────────────────────
    failed_step = "begin"
    last_error: Exception | None = None
    for delay in _RETRY_DELAYS:
        if delay:
            await asyncio.sleep(delay)
        try:
            async with AsyncSessionLocal() as db:
                async with db.begin():
                    failed_step = "close_visits"
                    await db.execute(_CLOSE_VISITS, {"sid": sid, "end_ms": shift_end_ms})
                    failed_step = "flush_zone_sessions"
                    await db.execute(_FLUSH_ZONES, {"sid": sid, "end_ms": shift_end_ms})
                    failed_step = "delete_active_person_state"
                    await db.execute(_DELETE_APS, {"sid": sid})
            last_error = None
            break
        except Exception as exc:
            last_error = exc
            log.warning("shift_closer: closing tx failed at step=%s store=%s (retrying): %s",
                        failed_step, store_id, exc)

    if last_error is not None:
        log.error("shift_closer: closing tx FAILED after retries store=%s step=%s — "
                  "alerting, NOT launching IEP5", store_id, failed_step)
        try:
            await email.send_shift_failure_alert(
                store_id, shift_date, failed_step, str(last_error),
            )
        except Exception:
            log.exception("shift_closer: failure-alert email also failed store=%s", store_id)
        return

    log.info("shift_closer: closed shift store=%s date=%s — launching IEP5", store_id, shift_date)

    # ── 4. Launch IEP5 ───────────────────────────────────────────────────────
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, iep5_manager.run_iep5_job, store_id, shift_date.isoformat())
