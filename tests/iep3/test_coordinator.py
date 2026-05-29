"""BatchCoordinator aggregation + timeout (no Redis)."""

from __future__ import annotations

import pytest

from services.iep3_reconciliation.app.coordinator import BatchCoordinator

pytestmark = pytest.mark.asyncio


class _Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def _recorder():
    fired: list = []

    async def on_ready(batch_number, window):
        fired.append((batch_number, window))

    return fired, on_ready


async def test_triggers_only_when_all_cameras_report():
    fired, on_ready = _recorder()
    coord = BatchCoordinator({"cam1", "cam2"}, on_ready=on_ready)

    assert await coord.note(0, "cam1", (0, 1000)) is False
    assert fired == []
    assert await coord.note(0, "cam2", (0, 1000)) is True
    assert fired == [(0, (0, 1000))]


async def test_independent_batches_tracked_separately():
    fired, on_ready = _recorder()
    coord = BatchCoordinator({"cam1", "cam2"}, on_ready=on_ready)
    await coord.note(0, "cam1", (0, 1000))
    await coord.note(1, "cam1", (1000, 2000))
    await coord.note(1, "cam2", (1000, 2000))  # batch 1 completes first
    assert [b for b, _ in fired] == [1]
    await coord.note(0, "cam2", (0, 1000))
    assert [b for b, _ in fired] == [1, 0]


async def test_timeout_triggers_partial_reconciliation():
    fired, on_ready = _recorder()
    clock = _Clock()
    coord = BatchCoordinator({"cam1", "cam2", "cam3"}, on_ready=on_ready,
                             timeout_seconds=120.0, clock=clock)

    await coord.note(5, "cam1", (0, 1000))  # only one of three cameras
    assert await coord.check_timeouts() == []  # not stale yet
    clock.t = 130.0
    assert await coord.check_timeouts() == [5]  # partial fire
    assert [b for b, _ in fired] == [5]
    # already fired -> not re-fired
    assert await coord.check_timeouts() == []
