import asyncio
import logging
import os
import uuid
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.core import iep2_docker
from app.core.config import settings
from app.grpc_generated import agent_pb2
from app.grpc_server import registry
from app.models.camera_runtime_session import CameraRuntimeSession

logger = logging.getLogger(__name__)

# EEP's own env vars — passed directly to IEP2 containers.
_DATABASE_URL    = os.environ.get("DATABASE_URL",    "")
_REDIS_URL       = os.environ.get("REDIS_URL",       "redis://redis:6379/0")
_S3_ENDPOINT_URL = os.environ.get("S3_ENDPOINT_URL", "")
_S3_ACCESS_KEY   = os.environ.get("S3_ACCESS_KEY",   "")
_S3_SECRET_KEY   = os.environ.get("S3_SECRET_KEY",   "")
_S3_BUCKET       = os.environ.get("S3_BUCKET",       "retailvision")

# In-memory map: (store_id, physical_camera_id) → open session UUID.
# Populated on camera start; drained on stop. Crash recovery re-populates from DB.
_open_sessions: dict[tuple[str, str], uuid.UUID] = {}

_LOAD_SQL = text("""
SELECT
    cc.id                                    AS camera_config_id,
    pc.id                                    AS physical_camera_id,
    pc.cloud_stream_url                      AS rtsp_url,
    COALESCE(ss.frame_sample_rate_fps, 5.0)  AS target_fps,
    scv.id                                   AS version_id
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


async def _open_session(
    db: AsyncSession,
    store_id: str,
    physical_camera_id: str,
    camera_config_id: str,
    version_id: str,
) -> uuid.UUID:
    session_obj = CameraRuntimeSession(
        store_id=uuid.UUID(store_id),
        physical_camera_id=uuid.UUID(physical_camera_id),
        camera_config_id=uuid.UUID(camera_config_id),
        version_id=uuid.UUID(version_id),
    )
    db.add(session_obj)
    session_id = session_obj.id  # uuid4 default is Python-side; capture before commit
    await db.commit()
    return session_id


async def _close_session(
    db: AsyncSession,
    store_id: str,
    physical_camera_id: str,
    stop_reason: str,
) -> None:
    session_id = _open_sessions.pop((store_id, physical_camera_id), None)
    if session_id is None:
        return
    await db.execute(
        text("""
            UPDATE camera_runtime_sessions
            SET stopped_at  = now(),
                stop_reason = :reason
            WHERE id = :id AND stopped_at IS NULL
        """),
        {"id": session_id, "reason": stop_reason},
    )
    await db.commit()


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
    version_id         = str(row["version_id"])

    # 1. Notify edge agent to start IEP1 (best-effort).
    ctrl = agent_pb2.ControlMessage(
        start_camera=agent_pb2.StartCamera(
            camera_id=physical_camera_id,
            store_id=store_id,
            rtsp_url=rtsp_url,
            target_fps=target_fps,
            window_seconds=settings.CAMERA_WINDOW_SECONDS,
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

    # 3. Record the session start (after Docker confirms, so partial failures leave no orphan rows).
    async with AsyncSessionLocal() as db:
        session_id = await _open_session(
            db, store_id, physical_camera_id, camera_config_id, version_id
        )
    _open_sessions[(store_id, physical_camera_id)] = session_id

    logger.info(
        "Camera workers started",
        extra={"store_id": store_id, "camera_config_id": camera_config_id},
    )


async def stop_camera_workers(
    store_id: str,
    camera_config_id: str,
    stop_reason: str = "unknown",
) -> None:
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

    # 3. Close the session record.
    async with AsyncSessionLocal() as db:
        await _close_session(db, store_id, physical_camera_id, stop_reason)

    logger.info(
        "Camera workers stopped",
        extra={"store_id": store_id, "camera_config_id": camera_config_id},
    )


async def activate_version_now(
    store_id: str,
    new_version_id: str,
    old_version_id: str | None = None,
    db=None,  # accepted for API compat; function always manages its own sessions
) -> tuple[list[str], list[str]]:
    """Stop old IEP2s, atomically flip version status, restart IEP2s on new configs.

    Returns (started_camera_config_ids, stopped_camera_config_ids).
    Callers are responsible for updating mark_running / mark_stopped accordingly.
    """
    # Step 1 — find cameras with open sessions for this store.
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text("""
                SELECT physical_camera_id, camera_config_id
                FROM camera_runtime_sessions
                WHERE store_id = :store_id
                  AND stopped_at IS NULL
                  AND physical_camera_id IS NOT NULL
                  AND camera_config_id   IS NOT NULL
            """),
            {"store_id": uuid.UUID(store_id)},
        )
        open_sessions = result.fetchall()

    # Step 2 — stop old IEP2 containers.
    stopped_config_ids: list[str] = []
    physical_camera_ids: list[str] = []
    for physical_camera_id, camera_config_id in open_sessions:
        await stop_camera_workers(
            store_id=store_id,
            camera_config_id=str(camera_config_id),
            stop_reason="version_activation",
        )
        stopped_config_ids.append(str(camera_config_id))
        physical_camera_ids.append(str(physical_camera_id))

    # Step 3 — atomically archive old version and activate new version.
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as session:
        async with session.begin():
            ver_result = await session.execute(
                text("SELECT status FROM store_config_versions WHERE id = :id"),
                {"id": uuid.UUID(new_version_id)},
            )
            ver_row = ver_result.first()
            if ver_row is None or ver_row[0] not in ("draft", "pending_activation"):
                raise ValueError(
                    f"Version {new_version_id} cannot be activated "
                    f"(current status: {ver_row[0] if ver_row else 'not found'})"
                )

            if old_version_id is not None:
                await session.execute(
                    text("""
                        UPDATE store_config_versions
                        SET status='archived', active_until=:now
                        WHERE id = :id
                    """),
                    {"id": uuid.UUID(old_version_id), "now": now},
                )

            await session.execute(
                text("""
                    UPDATE store_config_versions
                    SET status='active', active_from=:now, activate_at=NULL
                    WHERE id = :id
                """),
                {"id": uuid.UUID(new_version_id), "now": now},
            )

    # Step 4 — restart cameras using the new version's camera configs.
    started_config_ids: list[str] = []
    for physical_camera_id in physical_camera_ids:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                text("""
                    SELECT cc.id
                    FROM camera_configs cc
                    WHERE cc.version_id         = :new_version_id
                      AND cc.physical_camera_id = :physical_camera_id
                    LIMIT 1
                """),
                {
                    "new_version_id": uuid.UUID(new_version_id),
                    "physical_camera_id": uuid.UUID(physical_camera_id),
                },
            )
            row = result.first()

        if row is None:
            logger.warning(
                "activate_version_now: no camera config for physical_camera_id=%s "
                "in new version %s, skipping restart",
                physical_camera_id, new_version_id,
            )
            continue

        new_config_id = str(row[0])
        await start_camera_workers(store_id=store_id, camera_config_id=new_config_id)
        started_config_ids.append(new_config_id)

    logger.info(
        "activate_version_now: version %s is now active  "
        "stopped=%d  started=%d",
        new_version_id, len(stopped_config_ids), len(started_config_ids),
    )
    return started_config_ids, stopped_config_ids
