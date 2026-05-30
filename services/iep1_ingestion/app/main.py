"""IEP1 ingestion CLI worker -- one process per camera.

Samples a video source, writes JPEG frames to S3 under capture-time keys, and
publishes one window manifest per window to ``stream:iep1:{camera_id}``. The
orchestrator launches N of these with a shared ``--start-ms`` so timelines align.
(When live ingestion lands, swap VideoFileSource for RtspSource -- nothing else
changes.)
"""

from __future__ import annotations

import argparse
import asyncio
import os

from common.config import get_settings
from common.logging_conf import configure_logging
from common.s3 import S3Client
from services.iep1_ingestion.app.runtime import Iep1Runtime
from services.iep1_ingestion.app.source.video_source import VideoFileSource


async def _main(store_id: str, camera_id: str, video_path: str, start_ms: int) -> None:
    settings = get_settings()
    configure_logging("iep1-ingestion")

    metrics_port = os.getenv("METRICS_PORT")
    if metrics_port:
        from services.iep1_ingestion.app.health import start_metrics_server

        start_metrics_server(int(metrics_port))

    s3 = S3Client(settings)
    await s3.ensure_bucket()
    source = VideoFileSource(video_path, settings.sample_rate_fps, start_ms)
    runtime = Iep1Runtime(store_id, camera_id, settings, s3_client=s3)
    await runtime.run(source, start_ms)


def main() -> None:
    p = argparse.ArgumentParser(description="IEP1 ingestion worker (one process per camera)")
    p.add_argument("--store-id", required=True)
    p.add_argument("--camera-id", required=True)
    p.add_argument("--video", required=True)
    p.add_argument("--start-ms", type=int, required=True)
    a = p.parse_args()
    asyncio.run(_main(a.store_id, a.camera_id, a.video, a.start_ms))


if __name__ == "__main__":
    main()
