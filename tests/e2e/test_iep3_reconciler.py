"""
IEP3 integration test — 3-camera reconciliation scenario.
Requires live PostgreSQL with A1 schema applied.
No Redis, IEP1, IEP2, or EEP needed.

Run: pytest tests/e2e/test_iep3_reconciler.py -v -s
"""
from __future__ import annotations

import os
import sys
import uuid
import numpy as np
import asyncpg
import pytest

# Make IEP3 app importable from repo root
sys.path.insert(
    0,
    os.path.join(os.path.dirname(__file__), "..", "..",
                 "services", "iep3_reconciliation"),
)

from app.settings import Iep3Settings
from app.repository import Iep3Repository
from app.reconciler import Reconciler
from app.db import create_pool, close_pool

# ── Constants ─────────────────────────────────────────────────────────────────

# Strip +asyncpg prefix if present — asyncpg direct driver does not use it.
# Consistent with test_full_pipeline.py.
DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://retailvision:retailvision_dev@localhost:5432/retailvision",
).replace("postgresql+asyncpg://", "postgresql://")

CAM_01 = str(uuid.UUID(int=0xCAA_0001))
CAM_02 = str(uuid.UUID(int=0xCAA_0002))
CAM_03 = str(uuid.UUID(int=0xCAA_0003))

LOCAL_A1 = uuid.UUID(int=0xAAAA_0001)
LOCAL_A2 = uuid.UUID(int=0xAAAA_0002)
LOCAL_B1 = uuid.UUID(int=0xBBBB_0001)

WINDOW_START = 1_700_000_000_000
WINDOW_END   = 1_700_000_060_000
BATCH_NUMBER = 99  # unlikely to collide with real data


def _centroid_a() -> np.ndarray:
    """Person A appearance centroid — all-ones unit vector."""
    v = np.ones(2048, dtype=np.float32)
    return v / np.linalg.norm(v)


def _centroid_b() -> np.ndarray:
    """
    Person B appearance centroid — orthogonal to centroid_a.
    Cosine similarity with centroid_a ≈ 0 (far below 0.85 threshold).
    """
    v = np.zeros(2048, dtype=np.float32)
    v[0] = 1.0  # orthogonal to all-ones vector
    return v


def _make_settings(store_id: str) -> Iep3Settings:
    return Iep3Settings(
        database_url=DATABASE_URL,
        redis_url="redis://localhost:6379/0",
        store_id=store_id,
        expected_cameras=frozenset([CAM_01, CAM_02, CAM_03]),
        coordinator_timeout_s=120.0,
        reid_threshold=0.85,
        max_speed_mps=1.5,
        embedding_dim=2048,
        selection_weight_area=0.7,
        selection_weight_confidence=0.3,
        grace_seconds=300.0,
        default_frame_width=1920,   # used because no camera_runtime_sessions seeded
        default_frame_height=1080,
    )


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
async def db_pool():
    """Create asyncpg pool for test seeding and verification."""
    pool = await asyncpg.create_pool(dsn=DATABASE_URL, min_size=1, max_size=5)
    yield pool
    await pool.close()


@pytest.fixture
async def test_store(db_pool):
    """
    Insert a test user and test store.
    Yields store_id (str).
    Cleans up in reverse order on teardown.
    """
    user_id  = uuid.uuid4()
    store_id = uuid.uuid4()

    async with db_pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO users (id, account_type, email, password_hash,
                               auth_provider, name)
            VALUES ($1, 'owner', $2, 'x', 'local', 'IEP3 Test User')
            """,
            user_id,
            f"iep3-test-{user_id}@test.local",
        )
        await conn.execute(
            """
            INSERT INTO stores (id, name, slug, created_by)
            VALUES ($1, 'IEP3 Test Store', $2, $3)
            """,
            store_id,
            f"iep3-test-{store_id}",
            user_id,
        )

    yield str(store_id)

    # Cleanup: store CASCADE removes tracking_history, local_centroids,
    # global_identities (and all child IEP3 tables) automatically.
    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM stores WHERE id = $1", store_id)
        await conn.execute("DELETE FROM users  WHERE id = $1", user_id)


@pytest.fixture
async def seeded_batch(db_pool, test_store):
    """
    Seed tracking_history and local_centroids for the 3-camera scenario.
    Returns test_store_id.
    """
    store_id = uuid.UUID(test_store)

    centroid_a_bytes = _centroid_a().tobytes()
    centroid_b_bytes = _centroid_b().tobytes()

    async with db_pool.acquire() as conn:
        # ── tracking_history ──────────────────────────────────────────────
        # Person A on cam-01 (large bbox, moderate conf) — first seen
        await conn.execute(
            """
            INSERT INTO tracking_history
                (store_id, camera_id, local_id, timestamp_ms,
                 floor_x, floor_y, bbox_confidence, bbox_area)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            """,
            store_id, CAM_01, LOCAL_A1,
            WINDOW_START + 10_000,
            5.0, 3.0, 0.85, 200_000,
        )
        # Second row for LOCAL_A1 (later in window — last_seen_ts)
        await conn.execute(
            """
            INSERT INTO tracking_history
                (store_id, camera_id, local_id, timestamp_ms,
                 floor_x, floor_y, bbox_confidence, bbox_area)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            """,
            store_id, CAM_01, LOCAL_A1,
            WINDOW_START + 30_000,
            5.0, 3.0, 0.85, 200_000,
        )
        # Person A on cam-02 (smaller bbox, higher conf)
        await conn.execute(
            """
            INSERT INTO tracking_history
                (store_id, camera_id, local_id, timestamp_ms,
                 floor_x, floor_y, bbox_confidence, bbox_area)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            """,
            store_id, CAM_02, LOCAL_A2,
            WINDOW_START + 20_000,
            5.3, 3.1, 0.90, 80_000,
        )
        # Person B on cam-03
        await conn.execute(
            """
            INSERT INTO tracking_history
                (store_id, camera_id, local_id, timestamp_ms,
                 floor_x, floor_y, bbox_confidence, bbox_area)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            """,
            store_id, CAM_03, LOCAL_B1,
            WINDOW_START + 25_000,
            12.0, 8.0, 0.88, 60_000,
        )

        # ── local_centroids ───────────────────────────────────────────────
        # LA1 and LA2 share the same centroid direction (Person A)
        await conn.execute(
            """
            INSERT INTO local_centroids
                (local_id, camera_id, store_id, centroid, updated_at_batch)
            VALUES ($1, $2, $3, $4, $5)
            """,
            LOCAL_A1, CAM_01, store_id, centroid_a_bytes, BATCH_NUMBER,
        )
        await conn.execute(
            """
            INSERT INTO local_centroids
                (local_id, camera_id, store_id, centroid, updated_at_batch)
            VALUES ($1, $2, $3, $4, $5)
            """,
            LOCAL_A2, CAM_02, store_id, centroid_a_bytes, BATCH_NUMBER,
        )
        # LB1 has orthogonal centroid (Person B)
        await conn.execute(
            """
            INSERT INTO local_centroids
                (local_id, camera_id, store_id, centroid, updated_at_batch)
            VALUES ($1, $2, $3, $4, $5)
            """,
            LOCAL_B1, CAM_03, store_id, centroid_b_bytes, BATCH_NUMBER,
        )

    return test_store


# ── Test ──────────────────────────────────────────────────────────────────────

async def test_three_camera_reconciliation(db_pool, seeded_batch):
    """
    Full reconciliation of the 3-camera scenario. Verifies all 5 invariants.
    """
    store_id_str = seeded_batch
    store_id     = uuid.UUID(store_id_str)
    settings     = _make_settings(store_id_str)

    # Build real components against real DB
    pool = await create_pool(DATABASE_URL)
    repo = Iep3Repository(pool, embedding_dim=2048)

    # Startup orphan sweep (should remove 0 — clean DB state)
    swept = await repo.orphan_sweep()
    assert swept == 0, "No orphans expected before first reconciliation"

    reconciler = Reconciler(
        store_id=store_id_str,
        repo=repo,
        settings=settings,
    )

    # Run one full batch
    stats = await reconciler.process_batch(
        batch_number=BATCH_NUMBER,
        window=(WINDOW_START, WINDOW_END),
        reporting_cameras=frozenset([CAM_01, CAM_02, CAM_03]),
    )

    await close_pool()

    # ── Assert stats ──────────────────────────────────────────────────────
    assert stats["known_locals"]        == 0, "First batch — no known locals yet"
    assert stats["new_locals"]          == 3, "LA1, LA2, LB1 are all new"
    assert stats["new_globals_created"] == 2, "Person A and Person B — 2 GlobalIDs"
    assert stats["positions_written"]   == 2, "One canonical position per GlobalID"
    assert stats["newly_lost"]          == 0, "All GlobalIDs active — no absent ones"
    assert stats["newly_exited"]        == 0, "No grace period elapsed"

    async with db_pool.acquire() as conn:

        # ── Invariant 1: one active LocalID per camera per GlobalID ───────
        dupes = await conn.fetchval(
            """
            SELECT count(*)
            FROM (
                SELECT global_id, camera_id, count(*) AS cnt
                FROM global_local_mapping
                WHERE is_active = TRUE
                  AND global_id IN (
                      SELECT global_id FROM global_identities
                      WHERE store_id = $1
                  )
                GROUP BY global_id, camera_id
                HAVING count(*) > 1
            ) t
            """,
            store_id,
        )
        assert dupes == 0, "Invariant 1: duplicate active (global,camera) pairs found"

        # ── Invariant 2: cross-camera ReID only ───────────────────────────
        # LA2 (cam-02) must be linked to the SAME GlobalID as LA1 (cam-01)
        g_a1 = await conn.fetchval(
            """
            SELECT global_id FROM global_local_mapping
            WHERE local_id = $1 AND is_active = TRUE
            """,
            LOCAL_A1,
        )
        g_a2 = await conn.fetchval(
            """
            SELECT global_id FROM global_local_mapping
            WHERE local_id = $1 AND is_active = TRUE
            """,
            LOCAL_A2,
        )
        assert g_a1 is not None, "LA1 must be linked to a GlobalID"
        assert g_a2 is not None, "LA2 must be linked to a GlobalID"
        assert g_a1 == g_a2, "Invariant 2: LA1 and LA2 must share a GlobalID (same person)"

        g_b1 = await conn.fetchval(
            """
            SELECT global_id FROM global_local_mapping
            WHERE local_id = $1 AND is_active = TRUE
            """,
            LOCAL_B1,
        )
        assert g_b1 is not None, "LB1 must be linked to a GlobalID"
        assert g_b1 != g_a1, "Person B must have a different GlobalID from Person A"

        # ── Invariant 3: first_seen_ts ordering — LA1 before LA2 ──────────
        la1_linked = await conn.fetchval(
            """
            SELECT linked_at_ts FROM global_local_mapping
            WHERE local_id = $1 AND is_active = TRUE
            """,
            LOCAL_A1,
        )
        la2_linked = await conn.fetchval(
            """
            SELECT linked_at_ts FROM global_local_mapping
            WHERE local_id = $1 AND is_active = TRUE
            """,
            LOCAL_A2,
        )
        assert la1_linked <= la2_linked, \
            "Invariant 3: LA1 (earlier first_seen_ts) must be linked before LA2"

        # ── Invariant 4: exactly one gth row per GlobalID per batch ───────
        gth_rows = await conn.fetch(
            """
            SELECT global_id, source_camera, selection_score
            FROM global_tracking_history
            WHERE batch_number = $1
              AND store_id     = $2
            ORDER BY global_id
            """,
            BATCH_NUMBER,
            store_id,
        )
        assert len(gth_rows) == 2, \
            f"Invariant 4: expected 2 gth rows, got {len(gth_rows)}"

        gth_by_global = {r["global_id"]: r for r in gth_rows}
        assert g_a1 in gth_by_global, "G_A must have a gth row"
        assert g_b1 in gth_by_global, "G_B must have a gth row"

        # ── Winner camera for G_A: cam-01 (larger bbox wins) ──────────────
        # Scores at default 1920×1080 (no camera_runtime_sessions seeded):
        #   cam-01: 0.7*(200_000/2_073_600) + 0.3*0.85 ≈ 0.323
        #   cam-02: 0.7*(80_000/2_073_600)  + 0.3*0.90 ≈ 0.297
        g_a_winner_camera = gth_by_global[g_a1]["source_camera"]
        assert g_a_winner_camera == CAM_01, \
            f"G_A winner should be cam-01 (largest bbox), got {g_a_winner_camera}"

        # ── Winner camera for G_B: cam-03 (only option) ───────────────────
        g_b_winner_camera = gth_by_global[g_b1]["source_camera"]
        assert g_b_winner_camera == CAM_03, \
            f"G_B winner should be cam-03 (only camera), got {g_b_winner_camera}"

        # ── Invariant 5: IEP3 never wrote to IEP2 tables ─────────────────
        # tracking_history row count unchanged (still 4 rows seeded)
        th_count = await conn.fetchval(
            "SELECT count(*) FROM tracking_history WHERE store_id = $1",
            store_id,
        )
        assert th_count == 4, \
            f"Invariant 5: tracking_history must be unchanged (4 rows), got {th_count}"

        # local_centroids unchanged (still 3 rows seeded — not deleted yet,
        # no GlobalIDs exited in first batch)
        lc_count = await conn.fetchval(
            "SELECT count(*) FROM local_centroids WHERE store_id = $1",
            store_id,
        )
        assert lc_count == 3, \
            f"Invariant 5: local_centroids must be unchanged (3 rows), got {lc_count}"

        # ── State: all GlobalIDs active ───────────────────────────────────
        gi_rows = await conn.fetch(
            "SELECT global_id, state, lost_since_ts FROM global_identities "
            "WHERE store_id = $1",
            store_id,
        )
        assert len(gi_rows) == 2, f"Expected 2 GlobalIDs, got {len(gi_rows)}"
        for row in gi_rows:
            assert row["state"] == "active", \
                f"GlobalID {row['global_id']} should be active, got {row['state']}"
            assert row["lost_since_ts"] is None, \
                "lost_since_ts must be NULL for active GlobalIDs"

        # ── global_embeddings seeded correctly ────────────────────────────
        # G_A should have embeddings for both cam-01 and cam-02
        ge_a = await conn.fetch(
            "SELECT camera_id FROM global_embeddings WHERE global_id = $1",
            g_a1,
        )
        ge_cameras_a = {r["camera_id"] for r in ge_a}
        assert CAM_01 in ge_cameras_a, "G_A must have cam-01 embedding"
        assert CAM_02 in ge_cameras_a, "G_A must have cam-02 embedding"

        # G_B should have embedding for cam-03 only
        ge_b = await conn.fetch(
            "SELECT camera_id FROM global_embeddings WHERE global_id = $1",
            g_b1,
        )
        assert len(ge_b) == 1
        assert ge_b[0]["camera_id"] == CAM_03

        # ── Centroid round-trip: stored bytes decode correctly ─────────────
        stored = await conn.fetchval(
            "SELECT centroid FROM global_embeddings "
            "WHERE global_id = $1 AND camera_id = $2",
            g_a1, CAM_01,
        )
        decoded = np.frombuffer(bytes(stored), dtype=np.float32)
        expected = _centroid_a()
        similarity = float(np.dot(decoded / np.linalg.norm(decoded),
                                   expected / np.linalg.norm(expected)))
        assert similarity > 0.999, \
            f"Stored centroid does not match original (similarity={similarity})"

        # ── Mapping active link count: 3 active links total ───────────────
        active_links = await conn.fetchval(
            """
            SELECT count(*) FROM global_local_mapping glm
            JOIN global_identities gi ON gi.global_id = glm.global_id
            WHERE gi.store_id = $1 AND glm.is_active = TRUE
            """,
            store_id,
        )
        assert active_links == 3, \
            f"Expected 3 active links (LA1, LA2, LB1), got {active_links}"

        # ── global_identities last_floor_x/y populated ────────────────────
        positions_set = await conn.fetch(
            "SELECT global_id, last_floor_x, last_floor_y FROM global_identities "
            "WHERE store_id = $1",
            store_id,
        )
        for pos in positions_set:
            assert pos["last_floor_x"] is not None, \
                f"last_floor_x must be set for GlobalID {pos['global_id']}"
            assert pos["last_floor_y"] is not None, \
                f"last_floor_y must be set for GlobalID {pos['global_id']}"

    print(f"\nAll invariants verified. Stats: {stats}")


# ── State machine transition test ─────────────────────────────────────────────

async def test_lost_then_exited_transitions(db_pool, seeded_batch):
    """
    Run two batches:
      Batch N:   all 3 cameras report — 2 GlobalIDs created (ACTIVE)
      Batch N+1: no observations — ACTIVE→LOST for both GlobalIDs
    Then manipulate lost_since_ts to trigger LOST→EXITED in Batch N+2.
    """
    store_id_str = seeded_batch
    store_id     = uuid.UUID(store_id_str)
    settings     = _make_settings(store_id_str)

    pool = await create_pool(DATABASE_URL)
    repo = Iep3Repository(pool, embedding_dim=2048)
    reconciler = Reconciler(store_id_str, repo, settings)

    # Batch N: seed data already in DB, run first reconciliation
    await reconciler.process_batch(
        batch_number=BATCH_NUMBER,
        window=(WINDOW_START, WINDOW_END),
        reporting_cameras=frozenset([CAM_01, CAM_02, CAM_03]),
    )

    # Batch N+1: empty window (no observations)
    empty_start = WINDOW_END
    empty_end   = WINDOW_END + 60_000

    stats_n1 = await reconciler.process_batch(
        batch_number=BATCH_NUMBER + 1,
        window=(empty_start, empty_end),
        reporting_cameras=frozenset([CAM_01, CAM_02, CAM_03]),
    )

    assert stats_n1["newly_lost"] == 2, \
        "Both GlobalIDs should be LOST after empty batch"

    async with db_pool.acquire() as conn:
        lost_states = await conn.fetch(
            "SELECT state, lost_since_ts FROM global_identities "
            "WHERE store_id = $1",
            store_id,
        )
        for row in lost_states:
            assert row["state"]         == "lost"
            assert row["lost_since_ts"] == empty_end

        # Fake grace period expiry: push lost_since_ts back by grace_seconds + 1ms
        grace_ms = int(settings.grace_seconds * 1000)
        await conn.execute(
            "UPDATE global_identities SET lost_since_ts = $1 WHERE store_id = $2",
            empty_end - grace_ms - 1,
            store_id,
        )

    # Batch N+2: run cleanup — LOST→EXITED should fire
    next_start = empty_end
    next_end   = empty_end + 60_000

    stats_n2 = await reconciler.process_batch(
        batch_number=BATCH_NUMBER + 2,
        window=(next_start, next_end),
        reporting_cameras=frozenset([CAM_01, CAM_02, CAM_03]),
    )

    assert stats_n2["newly_exited"] == 2, \
        "Both GlobalIDs should EXIT after grace period"

    async with db_pool.acquire() as conn:
        # Verify state='exited'
        exited = await conn.fetchval(
            "SELECT count(*) FROM global_identities "
            "WHERE store_id = $1 AND state = 'exited'",
            store_id,
        )
        assert exited == 2

        # Verify mappings deactivated
        active_links = await conn.fetchval(
            """
            SELECT count(*) FROM global_local_mapping glm
            JOIN global_identities gi ON gi.global_id = glm.global_id
            WHERE gi.store_id = $1 AND glm.is_active = TRUE
            """,
            store_id,
        )
        assert active_links == 0, "All links must be deactivated after exit"

        # Verify centroids deleted
        lc_count = await conn.fetchval(
            "SELECT count(*) FROM local_centroids WHERE store_id = $1",
            store_id,
        )
        assert lc_count == 0, "All centroids must be deleted after GlobalID exit"

    await close_pool()
    print("\nState machine transitions verified: ACTIVE→LOST→EXITED")
