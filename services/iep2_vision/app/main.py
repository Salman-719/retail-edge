"""IEP2 service entrypoint / CLI worker.

For the video-input assumption, IEP2 runs as a CLI worker (not an HTTP server):
it is told which camera and video to process. One process is launched per camera;
M6's orchestrator launches N of these with a shared ``start_ms``. When IEP1
streaming returns, only this file and ``ingest/video_source.py`` change.
"""

from __future__ import annotations

import argparse
import asyncio

from sqlalchemy import select

from common.config import get_settings
from common.db.engine import dispose_engine, session_scope
from common.logging_conf import configure_logging
from common.models.shared_tables import CameraCalibration
from services.iep2_vision.app.runtime import Iep2Runtime


async def _main(store_id: str, camera_id: str, video_path: str, start_ms: int) -> None:
    get_settings()
    configure_logging("iep2-vision")
    async with session_scope() as session:
        cal = (
            await session.execute(select(CameraCalibration).where(CameraCalibration.cam_id == camera_id))
        ).scalar_one()
    runtime = Iep2Runtime(store_id, camera_id, get_settings())
    await runtime.setup(cal)
    await runtime.run(video_path, start_ms)
    await dispose_engine()


def main() -> None:
    p = argparse.ArgumentParser(description="IEP2 vision worker (one process per camera)")
    p.add_argument("--store-id", required=True)
    p.add_argument("--camera-id", required=True)
    p.add_argument("--video", required=True)
    p.add_argument("--start-ms", type=int, required=True)
    a = p.parse_args()
    asyncio.run(_main(a.store_id, a.camera_id, a.video, a.start_ms))


if __name__ == "__main__":
    main()
