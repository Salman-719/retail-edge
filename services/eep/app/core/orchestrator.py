import asyncio
import logging
import os

from sqlalchemy import text

from app.core.database import AsyncSessionLocal
from app.core import iep2_docker
from app.grpc_generated import agent_pb2
from app.grpc_server import registry

logger = logging.getLogger(__name__)

# EEP's own env vars — passed directly to IEP2 containers.
_DATABASE_URL    = os.environ.get("DATABASE_URL",    "")
_REDIS_URL       = os.environ.get("REDIS_URL",       "redis://redis:6379/0")
_S3_ENDPOINT_URL = os.environ.get("S3_ENDPOINT_URL", "")
_S3_ACCESS_KEY   = os.environ.get("S3_ACCESS_KEY",   "")
_S3_SECRET_KEY   = os.environ.get("S3_SECRET_KEY",   "")
_S3_BUCKET       = os.environ.get("S3_BUCKET",       "retailvision")

_LOAD_SQL = text("""
SELECT
    cc.id                                    AS camera_config_id,
    pc.id                                    AS physical_camera_id,
    pc.cloud_stream_url                      AS rtsp_url,
    COALESCE(ss.frame_sample_rate_fps, 5.0)  AS target_fps
FROM camera_configs cc
JOIN store_config_versions scv ON scv.id = cc.version_id
JOIN physical_cameras pc       ON pc.id  = cc.physical_camera_id
LEFT JOIN store_settings ss    ON ss.store_id = scv.store_id
WHERE cc.id        = :camera_config_id
  AND scv.store_id = :store_id
LIMIT 1
""")


async def _load_camera_data(session, store_id: str, camera_config_id: str) -> dict | None:
    result = await session.execute(
        _LOAD_SQL,
        {"camera_config_id": camera_config_id, "store_id": store_id},
    )
    row = result.first()
    return dict(row._mapping) if row is not None else None


async def start_camera_workers(store_id: str, camera_config_id: str) -> None:
    async with AsyncSessionLocal() as session:
        row = await _load_camera_data(session, store_id, camera_config_id)

    if row is None:
        logger.warning(
            "Camera data not found, skipping start",
            extra={"store_id": store_id, "camera_config_id": camera_config_id},
        )
        return

    physical_camera_id = str(row["physical_camera_id"])
    rtsp_url           = row["rtsp_url"] or ""
    target_fps         = float(row["target_fps"])

    # 1. Notify edge agent to start IEP1 (best-effort).
    ctrl = agent_pb2.ControlMessage(
        start_camera=agent_pb2.StartCamera(
            camera_id=physical_camera_id,
            store_id=store_id,
            rtsp_url=rtsp_url,
            target_fps=target_fps,
            window_seconds=60.0,
            redis_url=_REDIS_URL,
            s3_config=agent_pb2.S3Config(
                endpoint_url=_S3_ENDPOINT_URL,
                access_key=_S3_ACCESS_KEY,
                secret_key=_S3_SECRET_KEY,
                bucket=_S3_BUCKET,
            ),
        )
    )
    sent = await registry.send_command(store_id, ctrl)
    if not sent:
        logger.warning(
            "Edge agent not connected, IEP1 not started",
            extra={"store_id": store_id},
        )

    # 2. Start IEP2 container (mandatory).
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(
        None,
        iep2_docker.start_iep2,
        store_id,
        physical_camera_id,
        camera_config_id,
        _DATABASE_URL,
        _REDIS_URL,
        _S3_ENDPOINT_URL,
        _S3_ACCESS_KEY,
        _S3_SECRET_KEY,
        _S3_BUCKET,
    )
    logger.info(
        "Camera workers started",
        extra={"store_id": store_id, "camera_config_id": camera_config_id},
    )


async def stop_camera_workers(store_id: str, camera_config_id: str) -> None:
    async with AsyncSessionLocal() as session:
        row = await _load_camera_data(session, store_id, camera_config_id)

    if row is None:
        logger.warning(
            "Camera data not found, skipping stop",
            extra={"store_id": store_id, "camera_config_id": camera_config_id},
        )
        return

    physical_camera_id = str(row["physical_camera_id"])

    # 1. Notify edge agent to stop IEP1 (best-effort).
    ctrl = agent_pb2.ControlMessage(
        stop_camera=agent_pb2.StopCamera(
            camera_id=physical_camera_id,
            store_id=store_id,
        )
    )
    sent = await registry.send_command(store_id, ctrl)
    if not sent:
        logger.warning(
            "Edge agent not connected, IEP1 not stopped",
            extra={"store_id": store_id},
        )

    # 2. Stop IEP2 container (mandatory).
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(
        None,
        iep2_docker.stop_iep2,
        store_id,
        physical_camera_id,
    )
    logger.info(
        "Camera workers stopped",
        extra={"store_id": store_id, "camera_config_id": camera_config_id},
    )
