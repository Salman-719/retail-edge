"""
Tests for StateManager — ACTIVE/LOST/EXITED transitions.
Uses mocked repo to verify correct method calls and arguments.
"""
import pytest
from unittest.mock import MagicMock

from .conftest import (
    STORE_ID, GLOBAL_01, GLOBAL_02,
    WINDOW_START, WINDOW_END,
)
from app.state import StateManager


def fake_conn():
    return MagicMock()


class FakeStateRepo:
    """Stateful fake repo for StateManager tests."""
    def __init__(self, lost_ids=None, exited_ids=None):
        self._lost_ids   = lost_ids   or []
        self._exited_ids = exited_ids or []
        self.deactivated = []
        self.deleted_centroids_for = []

    async def transition_active_to_lost(self, conn, store_id,
                                         window_start_ms, window_end_ms):
        return list(self._lost_ids)

    async def transition_lost_to_exited(self, conn, store_id,
                                         grace_seconds, window_end_ms):
        return list(self._exited_ids)

    async def deactivate_mappings_for_globals(self, conn, global_ids, unlinked_at_ts):
        self.deactivated.extend(global_ids)

    async def delete_centroids_for_globals(self, conn, global_ids):
        self.deleted_centroids_for.extend(global_ids)


async def test_active_to_lost_calls_transition(settings):
    repo = FakeStateRepo(lost_ids=[GLOBAL_01])
    sm = StateManager(repo, settings)

    stats = await sm.run_cleanup(
        fake_conn(), STORE_ID, WINDOW_START, WINDOW_END
    )

    assert stats["newly_lost"] == 1
    assert stats["newly_exited"] == 0


async def test_lost_to_exited_deactivates_mappings(settings):
    repo = FakeStateRepo(exited_ids=[GLOBAL_01])
    sm = StateManager(repo, settings)

    await sm.run_cleanup(fake_conn(), STORE_ID, WINDOW_START, WINDOW_END)

    assert GLOBAL_01 in repo.deactivated


async def test_lost_to_exited_deletes_centroids(settings):
    repo = FakeStateRepo(exited_ids=[GLOBAL_01])
    sm = StateManager(repo, settings)

    await sm.run_cleanup(fake_conn(), STORE_ID, WINDOW_START, WINDOW_END)

    assert GLOBAL_01 in repo.deleted_centroids_for


async def test_no_exited_skips_deactivate_and_delete(settings):
    """When no GlobalIDs exit, deactivate and delete are not called."""
    repo = FakeStateRepo(exited_ids=[])
    sm = StateManager(repo, settings)

    await sm.run_cleanup(fake_conn(), STORE_ID, WINDOW_START, WINDOW_END)

    assert repo.deactivated == []
    assert repo.deleted_centroids_for == []


async def test_deactivate_before_delete_order(settings):
    """
    Invariant: deactivate_mappings_for_globals must be called before
    delete_centroids_for_globals (centroid deletion reads mapping table).
    """
    call_order = []
    repo = FakeStateRepo(exited_ids=[GLOBAL_01])

    original_deactivate = repo.deactivate_mappings_for_globals
    original_delete     = repo.delete_centroids_for_globals

    async def tracked_deactivate(conn, global_ids, unlinked_at_ts):
        call_order.append("deactivate")
        return await original_deactivate(conn, global_ids, unlinked_at_ts)

    async def tracked_delete(conn, global_ids):
        call_order.append("delete")
        return await original_delete(conn, global_ids)

    repo.deactivate_mappings_for_globals = tracked_deactivate
    repo.delete_centroids_for_globals    = tracked_delete

    sm = StateManager(repo, settings)
    await sm.run_cleanup(fake_conn(), STORE_ID, WINDOW_START, WINDOW_END)

    assert call_order == ["deactivate", "delete"], \
        "deactivate must precede delete"


async def test_empty_batch_returns_zeros(settings):
    repo = FakeStateRepo(lost_ids=[], exited_ids=[])
    sm = StateManager(repo, settings)

    stats = await sm.run_cleanup(
        fake_conn(), STORE_ID, WINDOW_START, WINDOW_END
    )

    assert stats == {"newly_lost": 0, "newly_exited": 0}
