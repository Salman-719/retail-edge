"""
Tests for ReidMatcher — Process 1 GlobalID linking.
Covers Architecture Spec §10 invariants 1, 2, 3.
Uses FakeRepo to simulate DB without a live connection.
"""
import uuid
import numpy as np
import pytest
from unittest.mock import MagicMock

from conftest import (
    STORE_ID, CAM_01, CAM_02, LOCAL_01, LOCAL_02, LOCAL_03,
    GLOBAL_01, WINDOW_START, WINDOW_END,
    make_obs, unit_vec, orthogonal_vec,
)
from app.reid.matcher import ReidMatcher
from app.repository import GlobalCandidate


# ── Fake connection (records calls, no real SQL) ──────────────────────────────

def fake_conn():
    """Lightweight asyncpg Connection stand-in."""
    return MagicMock()


# ── FakeRepo ──────────────────────────────────────────────────────────────────

class FakeRepo:
    """
    Stateful fake repository.
    Records create_global_identity, link_local, upsert_embedding,
    reactivate_global calls. Returns seeded centroids and candidates.
    """
    def __init__(self, centroids=None, candidates=None, embeddings=None):
        self._centroids  = centroids  or {}   # {local_id: np.ndarray}
        self._candidates = candidates or []   # list[GlobalCandidate]
        self._embeddings = embeddings or {}   # {global_id: [(cam, arr)]}

        self.created_globals     = []   # list of returned global_ids
        self.linked_pairs        = []   # list of (global_id, camera_id, local_id)
        self.reactivated         = []   # list of global_ids
        self.upserted_embeddings = []   # list of (global_id, camera_id)

        self._next_global = uuid.UUID(int=9000)

    async def get_candidate_globals(self, conn, store_id):
        return list(self._candidates)

    async def get_embeddings_bulk(self, conn, global_ids):
        return {gid: self._embeddings.get(gid, []) for gid in global_ids}

    async def load_local_centroid(self, conn, local_id):
        return self._centroids.get(local_id)

    async def create_global_identity(self, conn, store_id,
                                      first_seen_ts, last_floor_x, last_floor_y):
        gid = self._next_global
        self._next_global = uuid.UUID(int=self._next_global.int + 1)
        self.created_globals.append(gid)
        return gid

    async def link_local(self, conn, global_id, camera_id, local_id, linked_at_ts):
        self.linked_pairs.append((global_id, camera_id, local_id))

    async def upsert_embedding(self, conn, global_id, camera_id,
                                centroid_bytes, updated_at_ts):
        self.upserted_embeddings.append((global_id, camera_id))

    async def reactivate_global(self, conn, global_id, local_id, camera_id,
                                 linked_at_ts, last_seen_ts,
                                 last_floor_x, last_floor_y):
        self.reactivated.append(global_id)
        self.linked_pairs.append((global_id, camera_id, local_id))


def make_matcher(repo, settings_fixture):
    return ReidMatcher(
        repo=repo,
        reid_threshold=settings_fixture.reid_threshold,
        max_speed_mps=settings_fixture.max_speed_mps,
        embedding_dim=settings_fixture.embedding_dim,
    )


# ── Tests ─────────────────────────────────────────────────────────────────────

async def test_new_global_created_when_no_candidates(settings):
    """
    Invariant: unmatched new LocalID — exactly one new GlobalID.
    No candidates in DB — create_global_identity called once.
    """
    centroid = unit_vec()
    repo = FakeRepo(centroids={LOCAL_01: centroid})
    matcher = make_matcher(repo, settings)

    obs = [make_obs(local_id=LOCAL_01, camera_id=CAM_01)]
    n = await matcher.link_new_locals(
        fake_conn(), STORE_ID, obs, batch_number=1,
        window_end_ms=WINDOW_END,
    )

    assert n == 1
    assert len(repo.created_globals) == 1
    assert (repo.created_globals[0], CAM_01, LOCAL_01) in repo.linked_pairs


async def test_cross_camera_same_person_one_global(settings):
    """
    Invariant 3 (ordered processing) + cross-camera linking:
    CAM_01 obs first — creates GlobalID. CAM_02 obs second, same centroid,
    gate passes — links to same GlobalID. Result: 1 GlobalID, 2 links.
    """
    centroid = unit_vec()
    repo = FakeRepo(centroids={LOCAL_01: centroid, LOCAL_02: centroid})
    matcher = make_matcher(repo, settings)

    obs1 = make_obs(local_id=LOCAL_01, camera_id=CAM_01,
                    first_seen_ts=WINDOW_START + 5_000,
                    last_seen_ts=WINDOW_START + 30_000,
                    floor_x=5.0, floor_y=3.0)
    obs2 = make_obs(local_id=LOCAL_02, camera_id=CAM_02,
                    first_seen_ts=WINDOW_START + 8_000,  # later — second
                    last_seen_ts=WINDOW_START + 35_000,
                    floor_x=5.5, floor_y=3.2)

    n = await matcher.link_new_locals(
        fake_conn(), STORE_ID, [obs1, obs2],
        batch_number=1, window_end_ms=WINDOW_END,
    )

    assert n == 1, "Only one new GlobalID should be created"
    gid = repo.created_globals[0]
    linked_globals = [p[0] for p in repo.linked_pairs]
    assert linked_globals.count(gid) == 2, "Both cameras linked to same GlobalID"


async def test_same_camera_creates_separate_globals(settings):
    """
    Invariant 2: cross-camera ReID only.
    Two LocalIDs on the same camera — two separate GlobalIDs.
    (Same-camera continuity is IEP2's job.)
    """
    centroid = unit_vec()
    repo = FakeRepo(centroids={LOCAL_01: centroid, LOCAL_02: centroid})
    matcher = make_matcher(repo, settings)

    obs1 = make_obs(local_id=LOCAL_01, camera_id=CAM_01,
                    first_seen_ts=WINDOW_START + 1_000)
    obs2 = make_obs(local_id=LOCAL_02, camera_id=CAM_01,  # same camera
                    first_seen_ts=WINDOW_START + 2_000)

    n = await matcher.link_new_locals(
        fake_conn(), STORE_ID, [obs1, obs2],
        batch_number=1, window_end_ms=WINDOW_END,
    )

    assert n == 2, "Same camera — two separate GlobalIDs"
    assert len(repo.created_globals) == 2


async def test_below_threshold_creates_new_global(settings):
    """
    Low cosine similarity (orthogonal vectors) — below threshold — new GlobalID.
    """
    new_centroid      = unit_vec()
    existing_centroid = orthogonal_vec()  # similarity ≈ 0

    existing_global = uuid.UUID(int=500)
    existing_candidate = GlobalCandidate(
        global_id=existing_global,
        state='active',
        last_floor_x=5.0, last_floor_y=3.0,
        last_seen_ts=WINDOW_START - 10_000,
        active_camera_ids={CAM_02},  # different camera — eligible
    )
    repo = FakeRepo(
        centroids={LOCAL_01: new_centroid},
        candidates=[existing_candidate],
        embeddings={existing_global: [(CAM_02, existing_centroid)]},
    )
    matcher = make_matcher(repo, settings)

    obs = [make_obs(local_id=LOCAL_01, camera_id=CAM_01)]
    # obs is already a list — do not wrap in another list
    n = await matcher.link_new_locals(
        fake_conn(), STORE_ID, obs,
        batch_number=1, window_end_ms=WINDOW_END,
    )

    assert n == 1, "Low similarity — new GlobalID, not linked to existing"


async def test_lost_global_reactivated_on_match(settings):
    """
    LOST GlobalID with matching centroid and passing gate — reactivated.
    reactivate_global called, not create_global_identity.
    """
    centroid = unit_vec()
    lost_global = uuid.UUID(int=600)
    lost_candidate = GlobalCandidate(
        global_id=lost_global,
        state='lost',
        last_floor_x=5.0, last_floor_y=3.0,
        last_seen_ts=WINDOW_START - 5_000,
        active_camera_ids=set(),  # no active links (was lost)
    )
    repo = FakeRepo(
        centroids={LOCAL_01: centroid},
        candidates=[lost_candidate],
        embeddings={lost_global: [(CAM_02, centroid)]},  # same direction centroid
    )
    matcher = make_matcher(repo, settings)

    obs = [make_obs(local_id=LOCAL_01, camera_id=CAM_01)]
    n = await matcher.link_new_locals(
        fake_conn(), STORE_ID, obs,
        batch_number=1, window_end_ms=WINDOW_END,
    )

    assert n == 0, "Reactivation — no new GlobalID created"
    assert lost_global in repo.reactivated
    assert len(repo.created_globals) == 0


async def test_no_centroid_creates_new_global_with_warning(settings, caplog):
    """
    LocalID has no centroid in local_centroids — new GlobalID without ReID.
    Warning logged. Pipeline continues.
    """
    repo = FakeRepo(centroids={})  # no centroid for LOCAL_01
    matcher = make_matcher(repo, settings)

    obs = [make_obs(local_id=LOCAL_01, camera_id=CAM_01)]

    import logging
    with caplog.at_level(logging.WARNING, logger="app.reid.matcher"):
        n = await matcher.link_new_locals(
            fake_conn(), STORE_ID, obs,
            batch_number=1, window_end_ms=WINDOW_END,
        )

    assert n == 1, "No centroid — new GlobalID still created"
    assert "No centroid" in caplog.text
