"""IEP3 repository — all DB reads and writes.
No SQL lives anywhere else in IEP3. All business logic components receive
data structures and call methods here — they never construct queries.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

import asyncpg
import numpy as np

logger = logging.getLogger(__name__)

_QUERY_TIMEOUT   = 120.0   # transactional queries — inside batch transaction
_STANDALONE_TIMEOUT = 30.0 # standalone queries — acquire own connection


# =============================================================================
# Data structures — imported by all IEP3 components
# =============================================================================

@dataclass
class LocalObservation:
    local_id:        uuid.UUID
    camera_id:       str
    last_floor_x:    float
    last_floor_y:    float
    last_seen_ts:    int    # epoch ms from tracking_history
    first_seen_ts:   int    # epoch ms, used for ordering in ReID loop
    best_confidence: float
    best_bbox_area:  float


@dataclass
class MappingRow:
    id:           int
    global_id:    uuid.UUID
    camera_id:    str
    local_id:     uuid.UUID
    is_active:    bool
    last_seen_ts: int


@dataclass
class GlobalCandidate:
    global_id:         uuid.UUID
    state:             str        # 'active' or 'lost'
    last_floor_x:      float | None
    last_floor_y:      float | None
    last_seen_ts:      int
    active_camera_ids: set        # set[str] — cameras with active links


@dataclass
class PositionRow:
    global_id:        uuid.UUID
    local_id:         uuid.UUID
    camera_id:        str
    floor_x:          float
    floor_y:          float
    zone_id:          uuid.UUID | None
    timestamp_ms:     int
    bbox_confidence:  float
    bbox_area:        float
    needs_entry_zone: bool   # True when global_identities.entry_zone_id IS NULL


@dataclass
class GlobalPosition:
    """One global_tracking_history row to bulk-insert (SPEC-002).

    timestamp_ms is the 5s BUCKET boundary (floor(ts/5000)*5000), not the
    winning frame's raw timestamp — this is what ON CONFLICT (global_id,
    timestamp_ms) dedups on. store_id is constant per batch and passed
    separately to the bulk writer.
    """
    global_id:       uuid.UUID
    version_id:      str | None
    batch_number:    int
    timestamp_ms:    int            # bucket boundary
    floor_x:         float
    floor_y:         float
    zone_id:         uuid.UUID | None
    source_camera:   str
    source_local_id: uuid.UUID
    selection_score: float


@dataclass
class ResolutionResult:
    width:            int
    height:           int
    camera_config_id: str    # UUID as str — used as cache key in C6


@dataclass
class CameraBatchInfo:
    camera_config_id: str        # UUID as str — resolution cache key
    version_id:       str | None  # UUID as str — written to global_tracking_history


# =============================================================================
# Repository
# =============================================================================

class Iep3Repository:

    def __init__(self, pool: asyncpg.Pool, embedding_dim: int = 2048) -> None:
        self._pool = pool
        self._embedding_dim = embedding_dim

    # =========================================================================
    # STANDALONE — acquire own connection
    # =========================================================================

    async def get_expected_cameras_count(self, store_id: str) -> int:
        """Return count of cameras IEP3 should wait for before reconciling.

        Tries three sources in order:
        1. Active store config version (production path).
        2. Open camera_runtime_sessions (dev pipeline / no active version).
        3. Returns 1 as a last resort so reconciliation always fires.
        """
        async with self._pool.acquire() as conn:
            count = await conn.fetchval(
                """
                SELECT COUNT(cc.id)
                FROM camera_configs cc
                JOIN store_config_versions scv ON scv.id = cc.version_id
                WHERE scv.store_id = $1
                  AND scv.status   = 'active'
                """,
                uuid.UUID(store_id),
                timeout=_STANDALONE_TIMEOUT,
            )
            if count:
                return int(count)

            count = await conn.fetchval(
                """
                SELECT COUNT(DISTINCT physical_camera_id)
                FROM camera_runtime_sessions
                WHERE store_id             = $1
                  AND stopped_at           IS NULL
                  AND physical_camera_id   IS NOT NULL
                """,
                uuid.UUID(store_id),
                timeout=_STANDALONE_TIMEOUT,
            )
            if count:
                return int(count)

        return 1

    async def get_camera_resolution(
        self,
        camera_id: str,
    ) -> ResolutionResult | None:
        """Resolve frame dimensions using the fallback chain:
          1. physical_cameras.stream_width/height  (written by IEP2 at startup)
          2. camera_configs.video_width/height      (written by test run upload)
          3. calibrations.image_width/height        (from calibration files)
        Returns None if all sources are NULL — caller uses env var default.
        camera_id is the physical_camera UUID string.
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT
                    pc.stream_width,
                    pc.stream_height,
                    cc.video_width,
                    cc.video_height,
                    cal.image_width,
                    cal.image_height,
                    crs.camera_config_id::text AS camera_config_id
                FROM camera_runtime_sessions crs
                JOIN physical_cameras pc
                     ON pc.id = crs.physical_camera_id
                JOIN camera_configs cc
                     ON cc.id = crs.camera_config_id
                LEFT JOIN calibrations cal
                     ON cal.camera_config_id = crs.camera_config_id
                    AND cal.is_current = TRUE
                    AND cal.status IN ('ok', 'verified')
                WHERE crs.physical_camera_id = $1::uuid
                  AND crs.stopped_at IS NULL
                  AND crs.physical_camera_id IS NOT NULL
                LIMIT 1
                """,
                camera_id,
                timeout=_STANDALONE_TIMEOUT,
            )

        if row is None:
            return None

        width  = row["stream_width"]  or row["video_width"]  or row["image_width"]
        height = row["stream_height"] or row["video_height"] or row["image_height"]
        if not width or not height:
            return None

        return ResolutionResult(
            width=int(width),
            height=int(height),
            camera_config_id=row["camera_config_id"],
        )

    async def orphan_sweep(self, store_id: str) -> tuple[int, int]:
        """Remove partial state left by IEP3 crashes.

        Cleans two categories in one transaction:
          1. global_identities created but never tracked (Process 1 committed,
             Process 2 crashed before writing global_tracking_history).
             FK CASCADE on global_local_mapping and global_embeddings cleans
             rows referencing deleted globals.
          2. local_centroids with no active global_local_mapping
             (mapping was deactivated but centroid row was not deleted).

        Returns (deleted_globals, deleted_centroids).
        Called on IEP3 startup and every ORPHAN_SWEEP_INTERVAL_BATCHES batches.
        """
        store_uuid = uuid.UUID(store_id)
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                deleted_globals = await conn.fetchval(
                    """
                    WITH deleted AS (
                        DELETE FROM global_identities
                        WHERE store_id = $1
                          AND last_seen_ts = first_seen_ts
                          AND NOT EXISTS (
                              SELECT 1 FROM global_tracking_history gth
                              WHERE gth.global_id = global_identities.global_id
                          )
                        RETURNING global_id
                    )
                    SELECT COUNT(*) FROM deleted
                    """,
                    store_uuid,
                    timeout=_STANDALONE_TIMEOUT,
                )
                deleted_centroids = await conn.fetchval(
                    """
                    WITH deleted AS (
                        DELETE FROM local_centroids lc
                        WHERE lc.store_id = $1
                          AND NOT EXISTS (
                              SELECT 1 FROM global_local_mapping glm
                              WHERE glm.local_id  = lc.local_id
                                AND glm.is_active = TRUE
                          )
                        RETURNING local_id
                    )
                    SELECT COUNT(*) FROM deleted
                    """,
                    store_uuid,
                    timeout=_STANDALONE_TIMEOUT,
                )

        deleted_globals   = int(deleted_globals or 0)
        deleted_centroids = int(deleted_centroids or 0)

        _sweep_extra = {
            "store_id":          store_id,
            "deleted_globals":   deleted_globals,
            "deleted_centroids": deleted_centroids,
        }
        if deleted_globals > 0 or deleted_centroids > 0:
            logger.warning("Orphan sweep found stale data", extra=_sweep_extra)
        else:
            logger.info("Orphan sweep clean", extra=_sweep_extra)
        return deleted_globals, deleted_centroids

    async def delete_tracking_history_window(
        self,
        camera_ids: list[str],
        window_start_ms: int,
        window_end_ms: int,
    ) -> int:
        """Delete processed tracking_history rows for a batch window (SPEC-002).

        IEP3 owns tracking_history deletion. Runs AFTER the batch transaction
        commits, on its own connection — never inside the global_tracking_history
        insert transaction. Deletes by camera_id + timestamp window (not by
        global_id): faster, and covers unmatched local rows too. If this fails
        the rows simply remain and are re-deleted when the same window is
        reprocessed — IEP2 inserts are ON CONFLICT DO NOTHING, so leftovers are
        harmless. Returns the number of rows deleted.
        """
        if not camera_ids:
            return 0
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                """
                DELETE FROM tracking_history
                WHERE camera_id = ANY($1::text[])
                  AND timestamp_ms >= $2
                  AND timestamp_ms <  $3
                """,
                list(camera_ids),
                window_start_ms,
                window_end_ms,
                timeout=_STANDALONE_TIMEOUT,
            )
        # asyncpg returns a status string like "DELETE 240".
        try:
            return int(result.split()[-1])
        except (AttributeError, ValueError):
            return 0

    # =========================================================================
    # TRANSACTION — caller passes asyncpg Connection
    # =========================================================================

    async def read_batch_observations(
        self,
        conn: asyncpg.Connection,
        window_start_ms: int,
        window_end_ms: int,
    ) -> list[LocalObservation]:
        """Read all LocalIDs active in this batch window.

        Excludes rows with NULL floor coordinates (calibration canary guard).
        Ordered by first_seen_ts ASC for deterministic ReID processing.
        """
        rows = await conn.fetch(
            """
            SELECT
                local_id,
                camera_id,
                MAX(timestamp_ms)    AS last_seen_ts,
                MIN(timestamp_ms)    AS first_seen_ts,
                MAX(bbox_confidence) AS best_confidence,
                MAX(bbox_area)       AS best_bbox_area,
                (ARRAY_AGG(floor_x ORDER BY timestamp_ms DESC))[1] AS last_floor_x,
                (ARRAY_AGG(floor_y ORDER BY timestamp_ms DESC))[1] AS last_floor_y
            FROM tracking_history
            WHERE timestamp_ms >= $1
              AND timestamp_ms <  $2
              AND floor_x IS NOT NULL
              AND floor_y IS NOT NULL
            GROUP BY local_id, camera_id
            ORDER BY MIN(timestamp_ms) ASC
            """,
            window_start_ms,
            window_end_ms,
            timeout=_QUERY_TIMEOUT,
        )
        if not rows:
            return []

        result = []
        for r in rows:
            if r["last_floor_x"] is None or r["last_floor_y"] is None:
                logger.warning(
                    "Canary: NULL floor_x/y for local_id=%s camera=%s "
                    "— skipping (check calibration)",
                    r["local_id"], r["camera_id"],
                )
                continue
            result.append(LocalObservation(
                local_id=r["local_id"],
                camera_id=r["camera_id"],
                last_floor_x=float(r["last_floor_x"]),
                last_floor_y=float(r["last_floor_y"]),
                last_seen_ts=int(r["last_seen_ts"]),
                first_seen_ts=int(r["first_seen_ts"]),
                best_confidence=float(r["best_confidence"] or 0.0),
                best_bbox_area=float(r["best_bbox_area"] or 0.0),
            ))
        return result

    async def get_active_mapping(
        self,
        conn: asyncpg.Connection,
        local_id: uuid.UUID,
    ) -> MappingRow | None:
        row = await conn.fetchrow(
            """
            SELECT id, global_id, camera_id, local_id, is_active, last_seen_ts
            FROM global_local_mapping
            WHERE local_id = $1 AND is_active = TRUE
            """,
            local_id,
            timeout=_QUERY_TIMEOUT,
        )
        if row is None:
            return None
        return MappingRow(
            id=row["id"],
            global_id=row["global_id"],
            camera_id=row["camera_id"],
            local_id=row["local_id"],
            is_active=row["is_active"],
            last_seen_ts=int(row["last_seen_ts"]),
        )

    async def touch_link(
        self,
        conn: asyncpg.Connection,
        local_id: uuid.UUID,
        last_seen_ts: int,
    ) -> None:
        """Update last_seen_ts on the active mapping for a known LocalID."""
        await conn.execute(
            """
            UPDATE global_local_mapping
            SET last_seen_ts = $1
            WHERE local_id = $2 AND is_active = TRUE
            """,
            last_seen_ts,
            local_id,
            timeout=_QUERY_TIMEOUT,
        )

    async def load_local_centroid(
        self,
        conn: asyncpg.Connection,
        local_id: uuid.UUID,
    ) -> np.ndarray | None:
        """Load the IEP2 EMA centroid for a LocalID.

        Returns float32 numpy array of shape (embedding_dim,) or None.
        .copy() is mandatory — asyncpg returns a memoryview-backed buffer that
        is freed when the connection is returned to the pool.
        """
        row = await conn.fetchrow(
            "SELECT centroid FROM local_centroids WHERE local_id = $1",
            local_id,
            timeout=_QUERY_TIMEOUT,
        )
        if row is None or row["centroid"] is None:
            return None
        return np.frombuffer(row["centroid"], dtype=np.float32).copy()

    async def get_candidate_globals(
        self,
        conn: asyncpg.Connection,
        store_id: str,
    ) -> list[GlobalCandidate]:
        """Load all ACTIVE and LOST GlobalIDs for this store.

        Returns last known position and the set of cameras with active links.
        Used by the C5 matcher as the candidate pool for ReID.
        """
        rows = await conn.fetch(
            """
            SELECT
                gi.global_id,
                gi.state,
                gi.last_floor_x,
                gi.last_floor_y,
                gi.last_seen_ts,
                ARRAY_AGG(glm.camera_id)
                    FILTER (WHERE glm.is_active = TRUE) AS active_cameras
            FROM global_identities gi
            LEFT JOIN global_local_mapping glm
                   ON glm.global_id = gi.global_id
            WHERE gi.store_id = $1::uuid
              AND gi.state IN ('active', 'lost')
            GROUP BY gi.global_id, gi.state,
                     gi.last_floor_x, gi.last_floor_y, gi.last_seen_ts
            """,
            store_id,
            timeout=_QUERY_TIMEOUT,
        )
        return [
            GlobalCandidate(
                global_id=r["global_id"],
                state=r["state"],
                last_floor_x=float(r["last_floor_x"]) if r["last_floor_x"] is not None else None,
                last_floor_y=float(r["last_floor_y"]) if r["last_floor_y"] is not None else None,
                last_seen_ts=int(r["last_seen_ts"]),
                active_camera_ids=set(r["active_cameras"] or []),
            )
            for r in rows
        ]

    async def get_global_embeddings(
        self,
        conn: asyncpg.Connection,
        global_id: uuid.UUID,
    ) -> list[tuple[str, np.ndarray]]:
        """Load all per-camera centroids for a GlobalID.

        Returns list of (camera_id, float32_centroid_array).
        Representative centroid is computed by the caller — not stored.
        .copy() is mandatory — see load_local_centroid docstring.
        """
        rows = await conn.fetch(
            "SELECT camera_id, centroid FROM global_embeddings WHERE global_id = $1",
            global_id,
            timeout=_QUERY_TIMEOUT,
        )
        return [
            (r["camera_id"], np.frombuffer(r["centroid"], dtype=np.float32).copy())
            for r in rows
        ]

    async def create_global_identity(
        self,
        conn: asyncpg.Connection,
        store_id: str,
        first_seen_ts: int,
        last_floor_x: float,
        last_floor_y: float,
    ) -> uuid.UUID:
        """Insert a new GlobalID. Returns the generated UUID.

        last_floor_x/y are set immediately — calibration guarantee means the
        first observation always has valid floor coordinates.
        """
        row = await conn.fetchrow(
            """
            INSERT INTO global_identities
                (store_id, first_seen_ts, last_seen_ts,
                 last_floor_x, last_floor_y, state)
            VALUES ($1::uuid, $2, $2, $3, $4, 'active')
            RETURNING global_id
            """,
            store_id,
            first_seen_ts,
            last_floor_x,
            last_floor_y,
            timeout=_QUERY_TIMEOUT,
        )
        return row["global_id"]

    async def link_local(
        self,
        conn: asyncpg.Connection,
        global_id: uuid.UUID,
        camera_id: str,
        local_id: uuid.UUID,
        linked_at_ts: int,
    ) -> None:
        """Insert a new active mapping row.

        If a prior active row exists for this (global_id, camera_id) — same
        camera, different local_id after IEP2 restart — deactivate it first.
        The partial unique index enforces one active row per (global_id, camera_id).
        """
        await conn.execute(
            """
            UPDATE global_local_mapping
            SET is_active      = FALSE,
                unlinked_at_ts = $1
            WHERE global_id = $2
              AND camera_id  = $3
              AND is_active  = TRUE
            """,
            linked_at_ts,
            global_id,
            camera_id,
            timeout=_QUERY_TIMEOUT,
        )
        await conn.execute(
            """
            INSERT INTO global_local_mapping
                (global_id, camera_id, local_id,
                 is_active, linked_at_ts, last_seen_ts)
            VALUES ($1, $2, $3, TRUE, $4, $4)
            """,
            global_id,
            camera_id,
            local_id,
            linked_at_ts,
            timeout=_QUERY_TIMEOUT,
        )

    async def deactivate_mapping(
        self,
        conn: asyncpg.Connection,
        local_id: uuid.UUID,
        unlinked_at_ts: int,
    ) -> None:
        await conn.execute(
            """
            UPDATE global_local_mapping
            SET is_active      = FALSE,
                unlinked_at_ts = $1
            WHERE local_id = $2 AND is_active = TRUE
            """,
            unlinked_at_ts,
            local_id,
            timeout=_QUERY_TIMEOUT,
        )

    async def upsert_embedding(
        self,
        conn: asyncpg.Connection,
        global_id: uuid.UUID,
        camera_id: str,
        centroid_bytes: bytes,
        updated_at_ts: int,
    ) -> None:
        """UPSERT per-camera centroid. PK is (global_id, camera_id)."""
        await conn.execute(
            """
            INSERT INTO global_embeddings
                (global_id, camera_id, centroid, updated_at_ts)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (global_id, camera_id) DO UPDATE
                SET centroid      = EXCLUDED.centroid,
                    updated_at_ts = EXCLUDED.updated_at_ts
            """,
            global_id,
            camera_id,
            centroid_bytes,
            updated_at_ts,
            timeout=_QUERY_TIMEOUT,
        )

    async def reactivate_global(
        self,
        conn: asyncpg.Connection,
        global_id: uuid.UUID,
        local_id: uuid.UUID,
        camera_id: str,
        linked_at_ts: int,
        last_seen_ts: int,
        last_floor_x: float,
        last_floor_y: float,
    ) -> None:
        """Transition a LOST GlobalID back to ACTIVE.

        Resets lost_since_ts to NULL, updates last position, then links the
        new LocalID that triggered the re-entry.
        """
        await conn.execute(
            """
            UPDATE global_identities
            SET state         = 'active',
                lost_since_ts = NULL,
                last_seen_ts  = $1,
                last_floor_x  = $2,
                last_floor_y  = $3
            WHERE global_id = $4
            """,
            last_seen_ts,
            last_floor_x,
            last_floor_y,
            global_id,
            timeout=_QUERY_TIMEOUT,
        )
        await self.link_local(conn, global_id, camera_id, local_id, linked_at_ts)

    async def get_positions_for_selection(
        self,
        conn: asyncpg.Connection,
        store_id: str,
        window_start_ms: int,
        window_end_ms: int,
    ) -> list[PositionRow]:
        """Fetch all tracking_history rows for active GlobalIDs in this window.

        Single query for all GlobalIDs — selector groups by global_id in Python.
        Per-GlobalID N+1 queries would be catastrophic for a store with 50+ visitors.
        Only rows with valid floor coordinates (calibration guarantee).
        """
        rows = await conn.fetch(
            """
            SELECT
                glm.global_id,
                th.local_id,
                th.camera_id,
                th.floor_x,
                th.floor_y,
                th.zone_id,
                th.timestamp_ms,
                th.bbox_confidence,
                th.bbox_area,
                gi.entry_zone_id IS NULL AS needs_entry_zone
            FROM tracking_history th
            JOIN global_local_mapping glm ON glm.local_id = th.local_id
            JOIN global_identities gi     ON gi.global_id = glm.global_id
            WHERE gi.store_id    = $1::uuid
              AND gi.state       = 'active'
              AND glm.is_active  = TRUE
              AND th.timestamp_ms >= $2
              AND th.timestamp_ms <  $3
              AND th.floor_x IS NOT NULL
              AND th.floor_y IS NOT NULL
            """,
            store_id,
            window_start_ms,
            window_end_ms,
            timeout=_QUERY_TIMEOUT,
        )
        return [
            PositionRow(
                global_id=r["global_id"],
                local_id=r["local_id"],
                camera_id=r["camera_id"],
                floor_x=float(r["floor_x"]),
                floor_y=float(r["floor_y"]),
                zone_id=r["zone_id"],
                timestamp_ms=int(r["timestamp_ms"]),
                bbox_confidence=float(r["bbox_confidence"] or 0.0),
                bbox_area=float(r["bbox_area"] or 0.0),
                needs_entry_zone=bool(r["needs_entry_zone"]),
            )
            for r in rows
        ]

    async def write_global_positions_bulk(
        self,
        conn: asyncpg.Connection,
        store_id: str,
        rows: list[GlobalPosition],
    ) -> int:
        """Bulk-insert all per-bucket positions for a batch in one round trip.

        SPEC-002: one row per (global_id, 5s bucket). unnest avoids per-row
        round trips (12 buckets × N persons). ON CONFLICT (global_id,
        timestamp_ms) DO NOTHING makes batch replay idempotent — relies on the
        idx_gth_unique_bucket unique index from SPEC-001. Runs inside the
        caller's batch transaction. Returns the number of rows submitted.
        """
        if not rows:
            return 0

        store_uuid = uuid.UUID(store_id)

        def _to_uuid(v):
            return uuid.UUID(v) if isinstance(v, str) else v

        global_ids       = [r.global_id for r in rows]
        store_ids        = [store_uuid] * len(rows)
        version_ids      = [_to_uuid(r.version_id) for r in rows]
        batch_numbers    = [r.batch_number for r in rows]
        timestamps       = [r.timestamp_ms for r in rows]
        floor_xs         = [r.floor_x for r in rows]
        floor_ys         = [r.floor_y for r in rows]
        zone_ids         = [r.zone_id for r in rows]
        source_cameras   = [r.source_camera for r in rows]
        source_local_ids = [r.source_local_id for r in rows]
        scores           = [float(r.selection_score) for r in rows]

        await conn.execute(
            """
            INSERT INTO global_tracking_history
                (global_id, store_id, version_id, batch_number,
                 timestamp_ms, floor_x, floor_y, zone_id,
                 source_camera, source_local_id, selection_score)
            SELECT * FROM unnest(
                $1::uuid[], $2::uuid[], $3::uuid[], $4::bigint[],
                $5::bigint[], $6::float8[], $7::float8[], $8::uuid[],
                $9::text[], $10::uuid[], $11::float4[]
            )
            ON CONFLICT (global_id, timestamp_ms) DO NOTHING
            """,
            global_ids,
            store_ids,
            version_ids,
            batch_numbers,
            timestamps,
            floor_xs,
            floor_ys,
            zone_ids,
            source_cameras,
            source_local_ids,
            scores,
            timeout=_QUERY_TIMEOUT,
        )
        return len(rows)

    async def update_global_last_seen(
        self,
        conn: asyncpg.Connection,
        global_id: uuid.UUID,
        floor_x: float,
        floor_y: float,
        last_seen_ts: int,
        zone_id: uuid.UUID | None,
        set_entry_zone: bool,
        entry_zone_id: uuid.UUID | None = None,
    ) -> None:
        """Update last known position on global_identities.

        Called once per GlobalID per batch with the LATEST bucket's winner:
        last_seen_ts / last_floor / exit_zone_id (=zone_id) all track the most
        recent position. set_entry_zone=True only on first write (entry_zone_id
        column is NULL); COALESCE avoids overwriting a previously set entry.
        entry_zone_id (SPEC-002) is the EARLIEST bucket's zone for this batch —
        the true entry within a 60s batch that may span multiple 5s buckets;
        defaults to zone_id when not supplied.
        """
        if set_entry_zone:
            entry_zone = entry_zone_id if entry_zone_id is not None else zone_id
            await conn.execute(
                """
                UPDATE global_identities
                SET last_seen_ts  = $1,
                    last_floor_x  = $2,
                    last_floor_y  = $3,
                    entry_zone_id = COALESCE(entry_zone_id, $4),
                    exit_zone_id  = $5
                WHERE global_id = $6
                """,
                last_seen_ts, floor_x, floor_y, entry_zone, zone_id, global_id,
                timeout=_QUERY_TIMEOUT,
            )
        else:
            await conn.execute(
                """
                UPDATE global_identities
                SET last_seen_ts = $1,
                    last_floor_x = $2,
                    last_floor_y = $3,
                    exit_zone_id = $4
                WHERE global_id = $5
                """,
                last_seen_ts, floor_x, floor_y, zone_id, global_id,
                timeout=_QUERY_TIMEOUT,
            )

    async def transition_active_to_lost(
        self,
        conn: asyncpg.Connection,
        store_id: str,
        window_start_ms: int,
        window_end_ms: int,
    ) -> list[uuid.UUID]:
        """Mark ACTIVE GlobalIDs as LOST if unseen this batch window.

        Condition: no active mapping had last_seen_ts >= window_start_ms.
        Uses window_end_ms as lost_since_ts. Returns list of transitioned GlobalIDs.
        """
        rows = await conn.fetch(
            """
            UPDATE global_identities gi
            SET state         = 'lost',
                lost_since_ts = $1
            WHERE gi.store_id = $2::uuid
              AND gi.state    = 'active'
              AND NOT EXISTS (
                  SELECT 1 FROM global_local_mapping glm
                  WHERE glm.global_id    = gi.global_id
                    AND glm.is_active    = TRUE
                    AND glm.last_seen_ts >= $3
              )
            RETURNING global_id
            """,
            window_end_ms,
            store_id,
            window_start_ms,
            timeout=_QUERY_TIMEOUT,
        )
        return [r["global_id"] for r in rows]

    async def transition_lost_to_exited(
        self,
        conn: asyncpg.Connection,
        store_id: str,
        grace_seconds: float,
        window_end_ms: int,
    ) -> list[uuid.UUID]:
        """Mark LOST GlobalIDs as EXITED when the grace period has elapsed.

        Grace period: (window_end_ms - lost_since_ts) >= grace_seconds * 1000.
        Returns list of exited GlobalIDs for cascade cleanup.
        """
        grace_ms = int(grace_seconds * 1000)
        rows = await conn.fetch(
            """
            UPDATE global_identities
            SET state = 'exited'
            WHERE store_id          = $1::uuid
              AND state             = 'lost'
              AND ($2 - lost_since_ts) >= $3
            RETURNING global_id
            """,
            store_id,
            window_end_ms,
            grace_ms,
            timeout=_QUERY_TIMEOUT,
        )
        return [r["global_id"] for r in rows]

    async def deactivate_mappings_for_globals(
        self,
        conn: asyncpg.Connection,
        global_ids: list[uuid.UUID],
        unlinked_at_ts: int,
    ) -> None:
        """Deactivate all active mapping links for exited GlobalIDs."""
        if not global_ids:
            return
        await conn.execute(
            """
            UPDATE global_local_mapping
            SET is_active      = FALSE,
                unlinked_at_ts = $1
            WHERE global_id = ANY($2)
              AND is_active   = TRUE
            """,
            unlinked_at_ts,
            global_ids,
            timeout=_QUERY_TIMEOUT,
        )

    async def delete_centroids_for_globals(
        self,
        conn: asyncpg.Connection,
        global_ids: list[uuid.UUID],
    ) -> None:
        """Delete local_centroids rows for all LocalIDs linked to exited GlobalIDs.

        Called after mappings are deactivated so the subquery still finds them.
        """
        if not global_ids:
            return
        await conn.execute(
            """
            DELETE FROM local_centroids
            WHERE local_id IN (
                SELECT local_id FROM global_local_mapping
                WHERE global_id = ANY($1)
            )
            """,
            global_ids,
            timeout=_QUERY_TIMEOUT,
        )

    async def get_active_mappings_bulk(
        self,
        conn: asyncpg.Connection,
        local_ids: list[uuid.UUID],
    ) -> dict[uuid.UUID, "MappingRow"]:
        """Load active mappings for a set of LocalIDs in one query.

        Returns a dict keyed by local_id for O(1) classification in Python.
        LocalIDs with no active mapping are absent from the dict.
        """
        if not local_ids:
            return {}

        rows = await conn.fetch(
            """
            SELECT id, global_id, camera_id, local_id, is_active, last_seen_ts
            FROM global_local_mapping
            WHERE local_id = ANY($1)
              AND is_active = TRUE
            """,
            local_ids,
            timeout=_QUERY_TIMEOUT,
        )
        return {
            row["local_id"]: MappingRow(
                id=row["id"],
                global_id=row["global_id"],
                camera_id=row["camera_id"],
                local_id=row["local_id"],
                is_active=row["is_active"],
                last_seen_ts=int(row["last_seen_ts"]),
            )
            for row in rows
        }

    async def touch_links_bulk(
        self,
        conn: asyncpg.Connection,
        updates: list[tuple[uuid.UUID, int]],   # (local_id, last_seen_ts)
    ) -> None:
        """Update last_seen_ts for all known active LocalIDs in one statement.

        Uses unnest for a true single-round-trip bulk UPDATE.
        Safe to call with empty list — returns immediately.
        """
        if not updates:
            return

        local_ids  = [u[0] for u in updates]
        timestamps = [u[1] for u in updates]

        await conn.execute(
            """
            UPDATE global_local_mapping AS glm
            SET last_seen_ts = v.ts
            FROM unnest($1::uuid[], $2::bigint[]) AS v(lid, ts)
            WHERE glm.local_id = v.lid
              AND glm.is_active = TRUE
            """,
            local_ids,
            timestamps,
            timeout=_QUERY_TIMEOUT,
        )

    async def get_embeddings_bulk(
        self,
        conn: asyncpg.Connection,
        global_ids: list[uuid.UUID],
    ) -> dict[uuid.UUID, list[tuple[str, np.ndarray]]]:
        """Load all per-camera centroids for a set of GlobalIDs in one query.

        Returns dict: {global_id: [(camera_id, centroid_array), ...]}
        Used by ReidMatcher to build representative centroids without N+1 reads.
        .copy() is mandatory — asyncpg memoryview is freed on pool return.
        """
        if not global_ids:
            return {}

        rows = await conn.fetch(
            """
            SELECT global_id, camera_id, centroid
            FROM global_embeddings
            WHERE global_id = ANY($1)
            """,
            global_ids,
            timeout=_QUERY_TIMEOUT,
        )
        result: dict = {}
        for row in rows:
            gid = row["global_id"]
            arr = np.frombuffer(row["centroid"], dtype=np.float32).copy()
            result.setdefault(gid, []).append((row["camera_id"], arr))
        return result

    async def get_camera_batch_info_bulk(
        self,
        camera_ids: list[str],
    ) -> dict[str, "CameraBatchInfo"]:
        """Standalone method — acquires own connection.

        Returns current camera_config_id and version_id for each camera_id
        from the open camera_runtime_sessions row. Used by PositionSelector
        to build resolution cache keys and populate version_id on history rows.
        Cameras with no open session are absent from the result.
        """
        if not camera_ids:
            return {}

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT
                    physical_camera_id::text AS camera_id,
                    camera_config_id::text   AS camera_config_id,
                    version_id::text         AS version_id
                FROM camera_runtime_sessions
                WHERE physical_camera_id = ANY($1::uuid[])
                  AND stopped_at IS NULL
                  AND physical_camera_id IS NOT NULL
                """,
                camera_ids,
                timeout=_STANDALONE_TIMEOUT,
            )
        return {
            row["camera_id"]: CameraBatchInfo(
                camera_config_id=row["camera_config_id"],
                version_id=row["version_id"],
            )
            for row in rows
        }
