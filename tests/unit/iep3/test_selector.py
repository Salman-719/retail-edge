"""
Tests for PositionSelector — Process 2 scoring and winner selection.
Since SPEC-002 the selector writes one row per GlobalID per 5s bucket (was one
per batch); within a single bucket the best-camera winner is still unique.
Pure scoring tests need no DB — tested directly on _selection_score.
write_canonical_positions tested with mocked repo.
"""
import pytest
from unittest.mock import MagicMock

from conftest import (
    STORE_ID, CAM_01, CAM_02, CAM_03,
    LOCAL_01, LOCAL_02, LOCAL_03,
    GLOBAL_01, GLOBAL_02, WINDOW_START, WINDOW_END,
    make_pos,
)
from app.selection import _selection_score, PositionSelector


# ── Pure scoring tests (no mocks) ────────────────────────────────────────────

def test_score_full_frame_perfect_confidence():
    s = _selection_score(1920 * 1080, 1.0, 1920, 1080, 0.7, 0.3)
    assert abs(s - 1.0) < 1e-6


def test_score_zero_area_zero_confidence():
    s = _selection_score(0.0, 0.0, 1920, 1080, 0.7, 0.3)
    assert s == 0.0


def test_score_area_clamped_to_one():
    """bbox_area larger than frame — normalized_area clamped to 1.0."""
    s = _selection_score(1920 * 1080 * 2, 0.0, 1920, 1080, 0.7, 0.3)
    assert abs(s - 0.7) < 1e-6


def test_score_larger_bbox_beats_higher_confidence():
    """Large bbox low conf vs small bbox high conf — weights favour area."""
    s_large = _selection_score(500_000, 0.5, 1920, 1080, 0.7, 0.3)
    s_small = _selection_score(10_000,  0.99, 1920, 1080, 0.7, 0.3)
    assert s_large > s_small, "Larger bbox should win with 0.7 area weight"


def test_score_different_resolutions_normalize_correctly():
    """
    Same absolute bbox_area on different resolution cameras should
    produce different normalized scores (higher resolution — smaller fraction).
    """
    bbox_area = 50_000
    s_hd = _selection_score(bbox_area, 0.9, 1920, 1080, 0.7, 0.3)
    s_sd = _selection_score(bbox_area, 0.9,  640,  480, 0.7, 0.3)
    assert s_sd > s_hd, "Same bbox on SD camera = larger fraction of frame"


# ── Selector integration: winner selection per GlobalID ───────────────────────

class FakeSelectorRepo:
    """Minimal repo for PositionSelector unit tests."""
    def __init__(self, positions, cam_infos=None, resolutions=None):
        self._positions   = positions
        self._cam_infos   = cam_infos   or {}
        self._resolutions = resolutions or {}
        self.written      = []   # (global_id, source_camera, score)
        self.written_rows = []   # list[GlobalPosition] — full bucket rows
        self.last_seen_updates = []

    async def get_positions_for_selection(self, conn, store_id, start, end):
        return self._positions

    async def get_camera_batch_info_bulk(self, camera_ids):
        from app.repository import CameraBatchInfo
        return {
            cid: CameraBatchInfo(
                camera_config_id=self._cam_infos.get(cid, "cfg-default"),
                version_id=None,
            )
            for cid in camera_ids
        }

    async def get_camera_resolution(self, camera_id):
        if camera_id in self._resolutions:
            w, h = self._resolutions[camera_id]
            from app.repository import ResolutionResult
            return ResolutionResult(w, h, "cfg-default")
        return None

    async def write_global_positions_bulk(self, conn, store_id, rows):
        for r in rows:
            self.written.append((r.global_id, r.source_camera, float(r.selection_score)))
        self.written_rows.extend(rows)
        return len(rows)

    async def update_global_last_seen(self, conn, global_id, floor_x, floor_y,
                                       last_seen_ts, zone_id, set_entry_zone,
                                       entry_zone_id=None):
        self.last_seen_updates.append(global_id)


def fake_conn():
    return MagicMock()


async def test_best_camera_wins(settings):
    """
    GlobalID with 3 camera reports — highest score wins.
    CAM_01 has a very large bbox (72% of frame) vs small bbox high-conf
    cameras — area weight 0.7 means CAM_01 score dominates.

    Scores at 1920x1080 (2,073,600 px):
      CAM_01: 0.7 * (1_500_000/2_073_600) + 0.3 * 0.5  ≈ 0.657
      CAM_02: 0.7 * (50_000/2_073_600)   + 0.3 * 0.98  ≈ 0.311
      CAM_03: 0.7 * (100_000/2_073_600)  + 0.3 * 0.7   ≈ 0.244
    """
    positions = [
        make_pos(global_id=GLOBAL_01, camera_id=CAM_01,
                 bbox_area=1_500_000, bbox_confidence=0.5),
        make_pos(global_id=GLOBAL_01, camera_id=CAM_02,
                 bbox_area=50_000,    bbox_confidence=0.98),
        make_pos(global_id=GLOBAL_01, camera_id=CAM_03,
                 bbox_area=100_000,   bbox_confidence=0.7),
    ]
    repo = FakeSelectorRepo(
        positions=positions,
        resolutions={
            CAM_01: (1920, 1080),
            CAM_02: (1920, 1080),
            CAM_03: (1920, 1080),
        },
    )
    selector = PositionSelector(repo, settings)

    n = await selector.write_canonical_positions(
        fake_conn(), STORE_ID, 1, WINDOW_START, WINDOW_END
    )

    assert n == 1, "One GlobalID — one row written"
    assert len(repo.written) == 1
    winning_camera = repo.written[0][1]
    assert winning_camera == CAM_01, "Largest bbox should win with 0.7 weight"


async def test_one_row_per_global_id(settings):
    """
    Invariant 4: exactly one global_tracking_history row per GlobalID per batch.
    Two GlobalIDs — two written rows, not four.
    """
    positions = [
        make_pos(global_id=GLOBAL_01, camera_id=CAM_01,
                 local_id=LOCAL_01, bbox_area=100_000),
        make_pos(global_id=GLOBAL_01, camera_id=CAM_02,
                 local_id=LOCAL_02, bbox_area=80_000),
        make_pos(global_id=GLOBAL_02, camera_id=CAM_01,
                 local_id=LOCAL_03, bbox_area=90_000),
    ]
    repo = FakeSelectorRepo(
        positions=positions,
        resolutions={CAM_01: (1920, 1080), CAM_02: (1920, 1080)},
    )
    selector = PositionSelector(repo, settings)

    n = await selector.write_canonical_positions(
        fake_conn(), STORE_ID, 1, WINDOW_START, WINDOW_END
    )

    assert n == 2
    written_globals = [w[0] for w in repo.written]
    assert GLOBAL_01 in written_globals
    assert GLOBAL_02 in written_globals
    assert written_globals.count(GLOBAL_01) == 1  # exactly one per global
    assert written_globals.count(GLOBAL_02) == 1


async def test_buckets_split_into_separate_rows(settings):
    """SPEC-002: one GlobalID seen across 3 distinct 5s buckets → 3 rows, each
    stamped at its 5s bucket boundary (timestamp_ms % 5000 == 0)."""
    positions = [
        make_pos(global_id=GLOBAL_01, camera_id=CAM_01,
                 timestamp_ms=WINDOW_START + 1_234),
        make_pos(global_id=GLOBAL_01, camera_id=CAM_01,
                 timestamp_ms=WINDOW_START + 5_678),
        make_pos(global_id=GLOBAL_01, camera_id=CAM_01,
                 timestamp_ms=WINDOW_START + 12_999),
    ]
    repo = FakeSelectorRepo(positions=positions, resolutions={CAM_01: (1920, 1080)})
    selector = PositionSelector(repo, settings)

    n = await selector.write_canonical_positions(
        fake_conn(), STORE_ID, 1, WINDOW_START, WINDOW_END
    )

    assert n == 3, "Three distinct buckets — three rows"
    assert len(repo.written_rows) == 3
    bucket_ts = sorted(r.timestamp_ms for r in repo.written_rows)
    assert bucket_ts == [WINDOW_START, WINDOW_START + 5_000, WINDOW_START + 10_000]
    assert all(r.timestamp_ms % 5000 == 0 for r in repo.written_rows), \
        "stored timestamp must be the bucket boundary"


async def test_same_bucket_collapses_to_one_row(settings):
    """Two observations of one GlobalID in the SAME bucket collapse to a single
    row (per-bucket winner selection)."""
    positions = [
        make_pos(global_id=GLOBAL_01, camera_id=CAM_01,
                 timestamp_ms=WINDOW_START + 1_000, bbox_area=100_000),
        make_pos(global_id=GLOBAL_01, camera_id=CAM_02,
                 timestamp_ms=WINDOW_START + 2_000, bbox_area=80_000),
    ]
    repo = FakeSelectorRepo(
        positions=positions,
        resolutions={CAM_01: (1920, 1080), CAM_02: (1920, 1080)},
    )
    selector = PositionSelector(repo, settings)

    n = await selector.write_canonical_positions(
        fake_conn(), STORE_ID, 1, WINDOW_START, WINDOW_END
    )

    assert n == 1, "Same bucket — one row"
    assert repo.written_rows[0].timestamp_ms == WINDOW_START
    assert repo.written[0][1] == CAM_01, "Larger bbox wins within the bucket"


async def test_empty_positions_returns_zero(settings):
    repo = FakeSelectorRepo(positions=[])
    selector = PositionSelector(repo, settings)
    n = await selector.write_canonical_positions(
        fake_conn(), STORE_ID, 1, WINDOW_START, WINDOW_END
    )
    assert n == 0
    assert repo.written == []


async def test_resolution_cache_hit_skips_db_query(settings):
    """
    Second call with same (camera_id, camera_config_id) — no re-query.
    get_camera_resolution called only once despite two batches.
    """
    positions = [make_pos(global_id=GLOBAL_01, camera_id=CAM_01)]
    repo = FakeSelectorRepo(
        positions=positions,
        resolutions={CAM_01: (1920, 1080)},
    )
    # Track calls to get_camera_resolution
    original = repo.get_camera_resolution
    call_count = [0]

    async def tracked(camera_id):
        call_count[0] += 1
        return await original(camera_id)

    repo.get_camera_resolution = tracked

    selector = PositionSelector(repo, settings)

    # Run two batches
    await selector.write_canonical_positions(
        fake_conn(), STORE_ID, 1, WINDOW_START, WINDOW_END
    )
    await selector.write_canonical_positions(
        fake_conn(), STORE_ID, 2, WINDOW_START, WINDOW_END
    )

    assert call_count[0] == 1, "Resolution queried only on first batch (cache hit second time)"
