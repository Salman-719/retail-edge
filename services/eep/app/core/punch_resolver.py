"""Punch-in resolver (employee-linking, S4).

Background tick owned by EEP. Turns 'pending' punch_events into global_id links by
floor-position proximity, then captures the matched identity's appearance centroids
into employee_embeddings(source='punch_in') for future phase-2 re-attach.

Gated on the store having a punch_in_station in its ACTIVE config version: stores
without a punch machine do no work.

Match: at punch time T, pick the global_id from global_tracking_history nearest the
station's floor point within PUNCH_MATCH_WINDOW_MS, accepted only if within radius_m.
The link itself (global_identities + punch_events + employee_embeddings) is one atomic
transaction; the active_person_state mirror is best-effort (the table only exists once
migration 0010 has run — see ENV notes in specs/employee-linking).
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid

import numpy as np
from sqlalchemy import text

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.punch_ingest import now_ms

log = logging.getLogger(__name__)

_ACTIVE_STATIONS = text("""
    SELECT pis.store_id, pis.world_x, pis.world_y, pis.radius_m, pis.camera_config_id
    FROM punch_in_stations pis
    JOIN store_config_versions scv
      ON scv.id = pis.version_id AND scv.status = 'active'
""")

_PENDING = text("""
    SELECT id, employee_id, punched_at_ms
    FROM punch_events
    WHERE store_id = :sid AND status = 'pending' AND punched_at_ms <= :cutoff
    ORDER BY punched_at_ms ASC
""")

# Nearest observation to the station point within the time window.
_MATCH = text("""
    SELECT gth.global_id,
           sqrt(power(gth.floor_x - :px, 2) + power(gth.floor_y - :py, 2)) AS dist_m
    FROM global_tracking_history gth
    WHERE gth.store_id = :sid
      AND gth.timestamp_ms BETWEEN :t_lo AND :t_hi
    ORDER BY dist_m ASC, abs(gth.timestamp_ms - :t) ASC
    LIMIT 1
""")

_GET_LINK = text("SELECT employee_id FROM global_identities WHERE global_id = :gid")

_LINK_IDENTITY = text("""
    UPDATE global_identities
       SET is_employee = TRUE, employee_id = :emp
     WHERE global_id = :gid
""")

_CLOSE_PUNCH = text("""
    UPDATE punch_events
       SET status = 'linked', linked_global_id = :gid, match_distance_m = :dist,
           attempts = attempts + 1, last_attempt_at = now(), resolved_at = now()
     WHERE id = :pid
""")

_BUMP_ATTEMPT = text("""
    UPDATE punch_events
       SET attempts = attempts + 1, last_attempt_at = now()
     WHERE id = :pid
""")

_GIVE_UP = text("""
    UPDATE punch_events
       SET status = 'unmatched', attempts = attempts + 1,
           last_attempt_at = now(), resolved_at = now()
     WHERE id = :pid
""")

_GET_CENTROIDS = text("SELECT camera_id, centroid FROM global_embeddings WHERE global_id = :gid")

# Resolve a global_embeddings.camera_id (physical camera id, TEXT) to a camera_configs.id
# in the store's active version, for employee_embeddings attribution. NULL if unresolved.
_RESOLVE_CC = text("""
    SELECT cc.id
    FROM camera_configs cc
    JOIN store_config_versions scv ON scv.id = cc.version_id AND scv.status = 'active'
    WHERE cc.store_id = :sid AND cc.physical_camera_id::text = :cam
    LIMIT 1
""")

_INSERT_EMB = text("""
    INSERT INTO employee_embeddings (employee_id, embedding, source, camera_config_id, confidence)
    VALUES (:emp, CAST(:emb AS JSONB), 'punch_in', :cc, NULL)
""")

_MIRROR_APS = text("""
    UPDATE active_person_state
       SET is_employee = TRUE, employee_id = :emp, updated_at = now()
     WHERE store_id = :sid AND global_id = :gid
""")


async def _copy_centroids(db, store_id: uuid.UUID, gid: uuid.UUID, emp: uuid.UUID) -> int:
    """Snapshot the matched identity's per-camera centroids into employee_embeddings.

    Best-effort: a centroid is float32[2048] raw bytes in global_embeddings, stored as a
    JSON array in employee_embeddings(source='punch_in'). Skips silently if none exist.
    """
    rows = (await db.execute(_GET_CENTROIDS, {"gid": gid})).fetchall()
    copied = 0
    for r in rows:
        vec = np.frombuffer(r.centroid, dtype=np.float32).tolist()
        cc_id = (await db.execute(_RESOLVE_CC, {"sid": store_id, "cam": r.camera_id})).scalar()
        await db.execute(_INSERT_EMB, {"emp": emp, "emb": json.dumps(vec), "cc": cc_id})
        copied += 1
    return copied


async def _resolve_store(station: dict) -> None:
    """Resolve all eligible pending punches for one store/station."""
    sid = station["store_id"]
    px, py, radius = station["world_x"], station["world_y"], station["radius_m"]
    now = now_ms()
    cutoff = now - settings.PUNCH_SETTLE_MS

    async with AsyncSessionLocal() as db:
        pending = (await db.execute(_PENDING, {"sid": sid, "cutoff": cutoff})).fetchall()

    claimed: set[uuid.UUID] = set()  # global_ids linked in this pass (conflict guard)

    for p in pending:
        t = p.punched_at_ms
        async with AsyncSessionLocal() as db:
            row = (await db.execute(_MATCH, {
                "sid": sid, "px": px, "py": py,
                "t": t, "t_lo": t - settings.PUNCH_MATCH_WINDOW_MS,
                "t_hi": t + settings.PUNCH_MATCH_WINDOW_MS,
            })).first()

        matched = row is not None and row.dist_m is not None and row.dist_m <= radius
        gid = row.global_id if row is not None else None

        if matched and gid not in claimed:
            # Don't steal a global_id already linked to a different employee.
            async with AsyncSessionLocal() as db:
                existing = (await db.execute(_GET_LINK, {"gid": gid})).scalar()
            if existing is not None and existing != p.employee_id:
                log.warning("punch_resolver: gid=%s already linked to a different employee; "
                            "leaving punch=%s pending", gid, p.id)
                matched = False

        if matched and gid not in claimed:
            try:
                async with AsyncSessionLocal() as db:
                    async with db.begin():
                        await db.execute(_LINK_IDENTITY, {"emp": p.employee_id, "gid": gid})
                        n = await _copy_centroids(db, sid, gid, p.employee_id)
                        await db.execute(_CLOSE_PUNCH, {"gid": gid, "dist": float(row.dist_m), "pid": p.id})
                claimed.add(gid)
                log.info("punch_resolver: linked punch=%s employee=%s -> gid=%s dist=%.2fm centroids=%d",
                         p.id, p.employee_id, gid, row.dist_m, n)
                # Best-effort live-state mirror (active_person_state exists only post-0010).
                try:
                    async with AsyncSessionLocal() as db:
                        await db.execute(_MIRROR_APS, {"emp": p.employee_id, "sid": sid, "gid": gid})
                        await db.commit()
                except Exception as exc:
                    log.debug("punch_resolver: aps mirror skipped (punch=%s): %s", p.id, exc)
            except Exception:
                log.exception("punch_resolver: link tx failed for punch=%s", p.id)
            continue

        # No usable match this tick.
        async with AsyncSessionLocal() as db:
            if now - t >= settings.PUNCH_MAX_WAIT_MS:
                await db.execute(_GIVE_UP, {"pid": p.id})
                await db.commit()
                log.info("punch_resolver: punch=%s unmatched after max wait", p.id)
            else:
                await db.execute(_BUMP_ATTEMPT, {"pid": p.id})
                await db.commit()


async def _run_once() -> None:
    async with AsyncSessionLocal() as db:
        stations = [dict(r._mapping) for r in (await db.execute(_ACTIVE_STATIONS)).fetchall()]
    for station in stations:
        try:
            await _resolve_store(station)
        except Exception:
            log.exception("punch_resolver: store pass failed store=%s", station.get("store_id"))


async def run_forever() -> None:
    """Resolver tick loop. Never lets one bad pass kill the task."""
    log.info("punch_resolver started  interval=%.0fs settle=%dms window=%dms max_wait=%dms",
             settings.PUNCH_RESOLVER_INTERVAL_S, settings.PUNCH_SETTLE_MS,
             settings.PUNCH_MATCH_WINDOW_MS, settings.PUNCH_MAX_WAIT_MS)
    while True:
        try:
            await _run_once()
        except Exception:
            log.exception("punch_resolver: tick failed")
        await asyncio.sleep(settings.PUNCH_RESOLVER_INTERVAL_S)
