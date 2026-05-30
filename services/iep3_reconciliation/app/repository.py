"""The single DB layer for IEP3 -- all reads/writes of the four owned tables plus
the read of ``local_centroids``. Keeping every query here means schema-aware code
lives in one file. IEP3 NEVER writes IEP2 tables (invariant §5)."""

from __future__ import annotations

import uuid

import numpy as np
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from common.models.iep2_tables import LocalCentroid
from common.models.iep3_tables import (
    GlobalEmbedding,
    GlobalIdentity,
    GlobalLocalMapping,
    GlobalTrackingHistory,
)
from common.utils.embeddings import deserialize_embedding, serialize_embedding


class Iep3Repository:
    def __init__(self, settings):
        self._s = settings

    # ---- reads ----

    async def load_local_centroid(self, session, local_id) -> np.ndarray | None:
        blob = (
            await session.execute(select(LocalCentroid.centroid).where(LocalCentroid.local_id == local_id))
        ).scalar_one_or_none()
        return deserialize_embedding(blob) if blob is not None else None  # self-describing

    async def active_mapping_for(self, session, local_id) -> GlobalLocalMapping | None:
        return (
            await session.execute(
                select(GlobalLocalMapping).where(
                    GlobalLocalMapping.local_id == local_id,
                    GlobalLocalMapping.is_active == True,  # noqa: E712
                )
            )
        ).scalar_one_or_none()

    async def candidate_globals(self, session, store_id, states: tuple[str, ...]):
        """ACTIVE + LOST GlobalIDs with their per-camera centroids. The GlobalID's
        last known floor position rides on the ORM object (last_floor_x/y)."""
        ids = (
            await session.execute(
                select(GlobalIdentity).where(
                    GlobalIdentity.store_id == store_id, GlobalIdentity.state.in_(states)
                )
            )
        ).scalars().all()
        result = []
        for g in ids:
            cams = (
                await session.execute(
                    select(GlobalEmbedding).where(GlobalEmbedding.global_id == g.global_id)
                )
            ).scalars().all()
            centroids = {c.camera_id: deserialize_embedding(c.centroid) for c in cams}
            result.append((g, centroids))
        return result

    # ---- writes ----

    async def create_global(
        self, session, store_id, first_ts, last_ts, last_floor_x, last_floor_y
    ) -> uuid.UUID:
        gid = uuid.uuid4()
        session.add(
            GlobalIdentity(
                global_id=gid,
                store_id=store_id,
                first_seen_ts=first_ts,
                last_seen_ts=last_ts,
                state="active",
                lost_since_batch=None,
                last_floor_x=last_floor_x,
                last_floor_y=last_floor_y,
            )
        )
        await session.flush()  # make it visible to same-batch candidate queries
        return gid

    async def link(self, session, global_id, camera_id, local_id, batch) -> None:
        # Deactivate any existing active link for this camera+global (replacement case)
        await session.execute(
            update(GlobalLocalMapping)
            .where(
                GlobalLocalMapping.global_id == global_id,
                GlobalLocalMapping.camera_id == camera_id,
                GlobalLocalMapping.is_active == True,  # noqa: E712
            )
            .values(is_active=False, unlinked_at_batch=batch)
        )
        session.add(
            GlobalLocalMapping(
                global_id=global_id,
                camera_id=camera_id,
                local_id=local_id,
                is_active=True,
                linked_at_batch=batch,
                last_seen_batch=batch,
            )
        )
        await session.flush()

    async def touch_link(self, session, local_id, batch) -> None:
        await session.execute(
            update(GlobalLocalMapping)
            .where(
                GlobalLocalMapping.local_id == local_id,
                GlobalLocalMapping.is_active == True,  # noqa: E712
            )
            .values(last_seen_batch=batch)
        )

    async def upsert_global_centroid(self, session, global_id, camera_id, centroid, batch) -> None:
        stmt = pg_insert(GlobalEmbedding).values(
            global_id=global_id,
            camera_id=camera_id,
            centroid=serialize_embedding(centroid),
            updated_at_batch=batch,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["global_id", "camera_id"],
            set_=dict(centroid=stmt.excluded.centroid, updated_at_batch=stmt.excluded.updated_at_batch),
        )
        await session.execute(stmt)

    async def reactivate_if_lost(self, session, global_id, last_ts) -> None:
        await session.execute(
            update(GlobalIdentity)
            .where(GlobalIdentity.global_id == global_id, GlobalIdentity.state == "lost")
            .values(state="active", lost_since_batch=None, last_seen_ts=last_ts)
        )

    async def update_global_last_position(self, session, global_id, floor_x, floor_y, last_ts) -> None:
        await session.execute(
            update(GlobalIdentity)
            .where(GlobalIdentity.global_id == global_id)
            .values(last_floor_x=floor_x, last_floor_y=floor_y, last_seen_ts=last_ts)
        )

    async def write_global_position(self, session, **row) -> None:
        session.add(GlobalTrackingHistory(**row))
