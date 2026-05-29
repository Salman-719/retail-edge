"""Seed ``camera_calibrations`` rows for a demo store.

Writes one flat calibration row per camera (homography + zone polygons) so the
demo/e2e path can run without the full EEP onboarding pipeline. Production IEP2
reads the richer EEP-owned calibration tables instead.
"""

from __future__ import annotations

import argparse
import asyncio
import uuid

from sqlalchemy.dialects.postgresql import insert as pg_insert

from common.config import get_settings  # noqa: F401  (ensures settings load before engine)
from common.db.engine import dispose_engine, session_scope
from common.models.shared_tables import CameraCalibration

# Identity homography (pixel == floor) + one zone spanning a 1000x1000 plane.
IDENTITY_HOMOGRAPHY = [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0]
DEFAULT_ZONES = {
    "zones": [{"zone_id": "floor", "polygon": [[0, 0], [1000, 0], [1000, 1000], [0, 1000]]}]
}


async def seed_calibration(store_id, cam_ids: list[str], *, homography=None, zone_polygons=None) -> None:
    homography = homography or IDENTITY_HOMOGRAPHY
    zone_polygons = zone_polygons or DEFAULT_ZONES
    async with session_scope() as session:
        for cam_id in cam_ids:
            stmt = pg_insert(CameraCalibration).values(
                cam_id=cam_id, store_id=store_id, homography=homography, zone_polygons=zone_polygons
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["cam_id"],
                set_=dict(store_id=store_id, homography=homography, zone_polygons=zone_polygons),
            )
            await session.execute(stmt)


async def _main(store: str, cameras: list[str]) -> None:
    store_id = store if _is_uuid(store) else uuid.uuid5(uuid.NAMESPACE_DNS, store)
    await seed_calibration(store_id, cameras)
    await dispose_engine()


def _is_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
        return True
    except ValueError:
        return False


if __name__ == "__main__":  # pragma: no cover
    p = argparse.ArgumentParser(description="Seed demo camera_calibrations rows")
    p.add_argument("--store", required=True, help="store id (uuid) or name (hashed to a uuid)")
    p.add_argument("--cameras", required=True, help="comma-separated camera ids")
    a = p.parse_args()
    asyncio.run(_main(a.store, a.cameras.split(",")))
