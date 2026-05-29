"""State machine transitions against a real database."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from common.config import get_settings
from common.db.engine import session_scope
from services.iep3_reconciliation.app.repository import Iep3Repository
from services.iep3_reconciliation.app.state import StateManager
from tests.iep3.integration.seed import insert_global, insert_mapping, new_uuid

pytestmark = pytest.mark.asyncio
STORE = uuid.UUID("33333333-3333-3333-3333-333333333333")


async def _state(gid) -> str:
    async with session_scope() as s:
        return (await s.execute(text("SELECT state FROM global_identities WHERE global_id=:g"),
                                {"g": gid})).scalar_one()


async def test_active_to_lost_to_exited(pg):
    settings = get_settings()
    sm = StateManager(Iep3Repository(settings), settings)
    gid, lid = new_uuid(), new_uuid()
    await insert_global(gid, STORE, state="active")
    await insert_mapping(gid, "cam1", lid, last_seen_batch=0)  # last seen in batch 0

    # batch 1: no active mapping seen this batch -> ACTIVE -> LOST
    async with session_scope() as s:
        await sm.run_cleanup(s, batch=1)
    assert await _state(gid) == "lost"

    # after the grace period -> LOST -> EXITED, mapping deactivated
    exit_batch = 1 + settings.global_grace_batches
    async with session_scope() as s:
        result = await sm.run_cleanup(s, batch=exit_batch)
    assert result["exited"] == 1
    assert await _state(gid) == "exited"
    async with session_scope() as s:
        active = (await s.execute(text(
            "SELECT COUNT(*) FROM global_local_mapping WHERE global_id=:g AND is_active=TRUE"),
            {"g": gid})).scalar_one()
    assert active == 0


async def test_active_stays_active_when_seen_this_batch(pg):
    settings = get_settings()
    sm = StateManager(Iep3Repository(settings), settings)
    gid, lid = new_uuid(), new_uuid()
    await insert_global(gid, STORE, state="active")
    await insert_mapping(gid, "cam1", lid, last_seen_batch=4)

    async with session_scope() as s:
        await sm.run_cleanup(s, batch=4)  # seen this batch
    assert await _state(gid) == "active"
