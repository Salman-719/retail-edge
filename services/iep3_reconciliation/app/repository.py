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

EMBEDDING_DIM = 2048       # resnet50_msmt17 — must match IEP2


def merge_top_quality(
    existing: list[tuple[float, np.ndarray]],
    incoming: list[tuple[float, np.ndarray]],
    max_n: int,
) -> list[tuple[float, np.ndarray]]:
    """Merge two (quality_score, embedding) lists, keeping the top `max_n`.

    Used by Stage 8 to fold a matched local_centroids heap into the global
    embedding store. Deterministic: sorted by descending quality.
    """
    combined = list(existing) + list(incoming)
    combined.sort(key=lambda t: t[0], reverse=True)
    return combined[:max_n]


def _unpack_embeddings(raw: bytes | None, count: int) -> np.ndarray:
    """Unpack a packed embeddings BYTEA into a (count, EMBEDDING_DIM) float32 array."""
    if not raw or count <= 0:
        return np.empty((0, EMBEDDING_DIM), dtype=np.float32)
    return np.frombuffer(raw, dtype=np.float32).reshape(count, EMBEDDING_DIM).copy()


def _unpack_scores(raw: bytes | None, count: int) -> np.ndarray:
    if not raw or count <= 0:
        return np.zeros(max(count, 0), dtype=np.float32)
    return np.frombuffer(raw, dtype=np.float32).copy()


# =============================================================================
# Data structures — imported by all IEP3 components
# =============================================================================

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


@dataclass
class DetectionRow:
    """One raw tracking_history detection in a batch window (Stage 1).

    Floor coords are metres; camera_id is the physical-camera UUID string.
    """
    camera_id:       str
    local_id:        uuid.UUID
    timestamp_ms:    int
    floor_x:         float
    floor_y:         float
    bbox_confidence: float
    bbox_area:       float


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

    # =========================================================================
    # SPATIAL-VOTING MATCHER (Stages 0–8) — new pipeline
    # =========================================================================

    async def get_camera_overlap_edges(self, store_id: str) -> set[tuple[str, str]]:
        """Stage 0 — camera pairs that share a covered zone in the active version.

        Standalone (own connection). Returns physical-camera-id string pairs
        (matching tracking_history.camera_id). Empty if camera_zone_coverage is
        unpopulated — in which case no cross-camera matching occurs.
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT DISTINCT
                    cc1.physical_camera_id::text AS cam_a,
                    cc2.physical_camera_id::text AS cam_b
                FROM camera_zone_coverage czc1
                JOIN camera_zone_coverage czc2
                     ON czc1.zone_id = czc2.zone_id
                    AND czc1.camera_config_id <> czc2.camera_config_id
                JOIN camera_configs cc1 ON czc1.camera_config_id = cc1.id
                JOIN camera_configs cc2 ON czc2.camera_config_id = cc2.id
                JOIN store_config_versions scv ON scv.id = cc1.version_id
                WHERE scv.store_id = $1::uuid
                  AND scv.status   = 'active'
                  AND cc2.version_id = cc1.version_id
                  AND cc1.physical_camera_id <> cc2.physical_camera_id
                """,
                store_id,
                timeout=_STANDALONE_TIMEOUT,
            )
        return {(r["cam_a"], r["cam_b"]) for r in rows}

    async def read_window_detections(
        self,
        conn: asyncpg.Connection,
        store_id: str,
        window_start_ms: int,
        window_end_ms: int,
    ) -> list[DetectionRow]:
        """Stage 1 — all valid-floor detections in the window, ordered by time.

        One query across all cameras (selector groups in Python). NULL floor
        coords are excluded (uncalibrated). Window is [start, end) to match the
        bucketed PositionSelector and avoid boundary double-counting.
        """
        rows = await conn.fetch(
            """
            SELECT camera_id, local_id, timestamp_ms,
                   floor_x, floor_y, bbox_confidence, bbox_area
            FROM tracking_history
            WHERE store_id = $1::uuid
              AND timestamp_ms >= $2
              AND timestamp_ms <  $3
              AND floor_x IS NOT NULL
              AND floor_y IS NOT NULL
            ORDER BY timestamp_ms ASC
            """,
            store_id, window_start_ms, window_end_ms,
            timeout=_QUERY_TIMEOUT,
        )
        return [
            DetectionRow(
                camera_id=r["camera_id"],
                local_id=r["local_id"],
                timestamp_ms=int(r["timestamp_ms"]),
                floor_x=float(r["floor_x"]),
                floor_y=float(r["floor_y"]),
                bbox_confidence=float(r["bbox_confidence"] or 0.0),
                bbox_area=float(r["bbox_area"] or 0.0),
            )
            for r in rows
        ]

    async def get_local_heaps_bulk(
        self,
        conn: asyncpg.Connection,
        local_ids: list[uuid.UUID],
    ) -> dict[uuid.UUID, list[tuple[float, np.ndarray]]]:
        """Load packed embedding heaps for a set of LocalIDs.

        Returns {local_id: [(quality_score, embedding), ...]}. Used by Stage 3
        (appearance fallback — stack the embeddings) and Stage 8 (merge into the
        global embedding store). LocalIDs with no row / zero embeddings absent.
        """
        if not local_ids:
            return {}
        rows = await conn.fetch(
            """
            SELECT local_id, embeddings, embedding_count, quality_scores
            FROM local_centroids
            WHERE local_id = ANY($1)
            """,
            local_ids,
            timeout=_QUERY_TIMEOUT,
        )
        out: dict[uuid.UUID, list[tuple[float, np.ndarray]]] = {}
        for r in rows:
            count = int(r["embedding_count"] or 0)
            embs = _unpack_embeddings(r["embeddings"], count)
            scores = _unpack_scores(r["quality_scores"], count)
            if embs.size:
                out[r["local_id"]] = [(float(scores[i]), embs[i]) for i in range(count)]
        return out

    async def find_global_ids_for_locals(
        self,
        conn: asyncpg.Connection,
        local_ids: list[uuid.UUID],
    ) -> list[tuple[uuid.UUID, int]]:
        """Stage 5 — active GlobalIDs already linked to any of these LocalIDs.

        Returns [(global_id, first_seen_ts), ...] (distinct), used to attach a
        component to an existing identity and resolve merge conflicts.
        """
        if not local_ids:
            return []
        rows = await conn.fetch(
            """
            SELECT DISTINCT gi.global_id, gi.first_seen_ts
            FROM global_local_mapping glm
            JOIN global_identities gi ON gi.global_id = glm.global_id
            WHERE glm.local_id = ANY($1)
              AND glm.is_active = TRUE
            """,
            local_ids,
            timeout=_QUERY_TIMEOUT,
        )
        return [(r["global_id"], int(r["first_seen_ts"])) for r in rows]

    async def link_member(
        self,
        conn: asyncpg.Connection,
        global_id: uuid.UUID,
        camera_id: str,
        local_id: uuid.UUID,
        linked_at_ts: int,
        last_seen_ts: int,
    ) -> None:
        """Stage 5 — upsert one (camera_id, local_id) component member onto a GlobalID.

        Idempotent: if this exact active mapping already exists, only its
        last_seen_ts advances. Otherwise any prior active mapping for this
        (global_id, camera_id) is deactivated and a fresh active row inserted —
        the partial unique index enforces one active local per camera per global.
        """
        existing = await conn.fetchval(
            """
            SELECT 1 FROM global_local_mapping
            WHERE global_id = $1 AND camera_id = $2 AND local_id = $3
              AND is_active = TRUE
            """,
            global_id, camera_id, local_id,
            timeout=_QUERY_TIMEOUT,
        )
        if existing:
            await conn.execute(
                """
                UPDATE global_local_mapping
                SET last_seen_ts = GREATEST(last_seen_ts, $4)
                WHERE global_id = $1 AND camera_id = $2 AND local_id = $3
                  AND is_active = TRUE
                """,
                global_id, camera_id, local_id, last_seen_ts,
                timeout=_QUERY_TIMEOUT,
            )
            return

        await conn.execute(
            """
            UPDATE global_local_mapping
            SET is_active = FALSE, unlinked_at_ts = $1
            WHERE global_id = $2 AND camera_id = $3 AND is_active = TRUE
            """,
            linked_at_ts, global_id, camera_id,
            timeout=_QUERY_TIMEOUT,
        )
        await conn.execute(
            """
            INSERT INTO global_local_mapping
                (global_id, camera_id, local_id, is_active, linked_at_ts, last_seen_ts)
            VALUES ($1, $2, $3, TRUE, $4, $5)
            """,
            global_id, camera_id, local_id, linked_at_ts, last_seen_ts,
            timeout=_QUERY_TIMEOUT,
        )

    async def merge_globals(
        self,
        conn: asyncpg.Connection,
        keep_global_id: uuid.UUID,
        discard_global_ids: list[uuid.UUID],
        window_end_ms: int,
    ) -> None:
        """Stage 5 merge conflict — exit the losing GlobalIDs of a component.

        Deactivates their active mappings and marks them 'exited'. Component
        members are then (re)linked to keep_global_id by the caller via
        link_member. Never raises on an empty discard list.
        """
        if not discard_global_ids:
            return
        await conn.execute(
            """
            UPDATE global_local_mapping
            SET is_active = FALSE, unlinked_at_ts = $1
            WHERE global_id = ANY($2) AND is_active = TRUE
            """,
            window_end_ms, discard_global_ids,
            timeout=_QUERY_TIMEOUT,
        )
        await conn.execute(
            """
            UPDATE global_identities
            SET state = 'exited'
            WHERE global_id = ANY($1)
            """,
            discard_global_ids,
            timeout=_QUERY_TIMEOUT,
        )

    async def get_global_embeddings_packed(
        self,
        conn: asyncpg.Connection,
        global_id: uuid.UUID,
        camera_id: str,
    ) -> list[tuple[float, np.ndarray]]:
        """Stage 8 — load the existing (global_id, camera_id) embedding heap.

        Returns a list of (quality_score, embedding) pairs (possibly empty).
        """
        row = await conn.fetchrow(
            """
            SELECT embeddings, embedding_count, quality_scores
            FROM global_embeddings
            WHERE global_id = $1 AND camera_id = $2
            """,
            global_id, camera_id,
            timeout=_QUERY_TIMEOUT,
        )
        if row is None:
            return []
        count = int(row["embedding_count"] or 0)
        embs = _unpack_embeddings(row["embeddings"], count)
        scores = _unpack_scores(row["quality_scores"], count)
        return [(float(scores[i]), embs[i]) for i in range(count)]

    async def upsert_global_embedding_packed(
        self,
        conn: asyncpg.Connection,
        global_id: uuid.UUID,
        camera_id: str,
        heap: list[tuple[float, np.ndarray]],
        updated_at_ts: int,
    ) -> None:
        """Stage 8 — write a merged embedding heap for (global_id, camera_id)."""
        if not heap:
            return
        embs = np.array([e for _, e in heap], dtype=np.float32)
        scores = np.array([q for q, _ in heap], dtype=np.float32)
        await conn.execute(
            """
            INSERT INTO global_embeddings
                (global_id, camera_id, embeddings, embedding_count,
                 quality_scores, updated_at_ts)
            VALUES ($1, $2, $3, $4, $5, $6)
            ON CONFLICT (global_id, camera_id) DO UPDATE
                SET embeddings      = EXCLUDED.embeddings,
                    embedding_count = EXCLUDED.embedding_count,
                    quality_scores  = EXCLUDED.quality_scores,
                    updated_at_ts   = EXCLUDED.updated_at_ts
            """,
            global_id, camera_id, embs.tobytes(), len(heap),
            scores.tobytes(), updated_at_ts,
            timeout=_QUERY_TIMEOUT,
        )
