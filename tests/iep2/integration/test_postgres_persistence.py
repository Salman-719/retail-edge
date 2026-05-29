"""PostgresPersistence against a real test database."""

from __future__ import annotations

import uuid

import numpy as np
import pytest
from sqlalchemy import text

from common.db.engine import session_scope
from common.utils.embeddings import deserialize_embedding
from services.iep2_vision.app.identity.pools import TempPosition
from services.iep2_vision.app.persistence.postgres import PostgresPersistence

pytestmark = pytest.mark.asyncio


async def _count(table: str) -> int:
    async with session_scope() as s:
        return (await s.execute(text(f"SELECT COUNT(*) FROM {table}"))).scalar_one()


async def test_positions_buffered_until_flush(pg):
    from common.config import get_settings

    db = PostgresPersistence(get_settings())
    lid = uuid.uuid4()
    db.append_position(lid, "cam1", 1000, 1.0, 2.0, "A", 0.9, 5000.0)
    db.append_position(lid, "cam1", 1200, 1.1, 2.1, "A", 0.9, 5000.0)
    assert await _count("tracking_history") == 0  # still buffered

    await db.maybe_flush(force=True)
    assert await _count("tracking_history") == 2


async def test_flush_temp_positions_writes_with_camera(pg):
    from common.config import get_settings

    db = PostgresPersistence(get_settings())
    lid = uuid.uuid4()
    positions = [TempPosition(1000 + i, float(i), float(i), "A", 0.8, 4000.0) for i in range(3)]
    db.flush_temp_positions(lid, "cam2", positions)
    await db.maybe_flush(force=True)
    async with session_scope() as s:
        rows = (await s.execute(text("SELECT camera_id FROM tracking_history"))).scalars().all()
    assert len(rows) == 3 and set(rows) == {"cam2"}


async def test_embedding_round_trips(pg):
    from common.config import get_settings

    settings = get_settings()
    db = PostgresPersistence(settings)
    lid = uuid.uuid4()
    vec = np.linspace(-1, 1, settings.embedding_dim).astype(np.float32)
    await db.write_embedding(lid, "cam1", 1000, vec, 0.9, True)
    async with session_scope() as s:
        blob = (await s.execute(text("SELECT embedding FROM local_embeddings WHERE local_id=:l"),
                                {"l": lid})).scalar_one()
    np.testing.assert_allclose(deserialize_embedding(blob, settings.embedding_dim), vec, atol=1e-6)


async def test_centroid_upsert_in_place(pg):
    from common.config import get_settings

    settings = get_settings()
    db = PostgresPersistence(settings)
    lid = uuid.uuid4()
    await db.upsert_centroid(lid, "cam1", np.zeros(settings.embedding_dim, np.float32), batch_number=1)
    await db.upsert_centroid(lid, "cam1", np.ones(settings.embedding_dim, np.float32), batch_number=4)
    async with session_scope() as s:
        rows = (await s.execute(text("SELECT updated_at_batch FROM local_centroids WHERE local_id=:l"),
                                {"l": lid})).scalars().all()
    assert rows == [4]  # one row, updated in place
