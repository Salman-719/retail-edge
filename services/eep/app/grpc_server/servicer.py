import asyncio
import logging
import uuid
from datetime import datetime, timezone

import grpc
from sqlalchemy import text

from app.core.database import AsyncSessionLocal
from app.grpc_generated import agent_pb2, agent_pb2_grpc
from app.grpc_server import camera_status, registry
from app.tasks import camera_scheduler

logger = logging.getLogger(__name__)


class AgentServiceServicer(agent_pb2_grpc.AgentServiceServicer):

    async def Connect(self, request_iterator, context):
        store_id = None
        _registered = False  # True only after a successful online upsert
        try:
            first = await request_iterator.__anext__()
            if not first.HasField("heartbeat"):
                # Wrap abort() — grpc.aio raises AbortError by design after setting status.
                try:
                    await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "First message must be Heartbeat")
                except Exception:
                    pass
                return

            store_id = first.heartbeat.store_id
            agent_version = first.heartbeat.agent_version
            logger.info("Agent connected", extra={"store_id": store_id, "version": agent_version})

            queue = await registry.register(store_id)
            ok = await _upsert_agent(store_id, agent_version, status="online")
            if not ok:
                registry.deregister(store_id)
                logger.warning("Agent rejected: store not found", extra={"store_id": store_id})
                try:
                    await context.abort(grpc.StatusCode.NOT_FOUND, f"Store {store_id} not found")
                except Exception:
                    pass
                return

            _registered = True

            reader_task = asyncio.create_task(_reader(request_iterator, store_id))
            writer_task = asyncio.create_task(_writer(queue, context))

            done, pending = await asyncio.wait(
                [reader_task, writer_task],
                return_when=asyncio.FIRST_COMPLETED,
            )
            for t in pending:
                t.cancel()
                try:
                    await t
                except asyncio.CancelledError:
                    pass

        except Exception as exc:
            logger.warning("Agent stream error", exc_info=exc, extra={"store_id": store_id})
        finally:
            if store_id:
                registry.deregister(store_id)
                if _registered:
                    await _upsert_agent(store_id, status="offline")
                logger.info("Agent disconnected", extra={"store_id": store_id})


async def _reader(request_iterator, store_id: str) -> None:
    async for msg in request_iterator:
        if msg.HasField("heartbeat"):
            await _upsert_agent(store_id, msg.heartbeat.agent_version, status="online")
        elif msg.HasField("camera_status"):
            await _handle_camera_status_report(store_id, msg.camera_status)


# ── CameraStatusReport handler (R4) ───────────────────────────────────────────

_CAMERA_CONFIG_LOOKUP_SQL = text("""
    SELECT cc.id AS camera_config_id
    FROM camera_configs cc
    JOIN store_config_versions scv ON scv.id = cc.version_id
    WHERE cc.physical_camera_id = :physical_camera_id
      AND scv.store_id           = :store_id
      AND scv.status             = 'active'
    LIMIT 1
""")


async def _handle_camera_status_report(store_id: str, rpt) -> None:
    """Update in-memory status, Redis _running_cameras, and scheduler state (R4)."""
    camera_id        = rpt.camera_id
    container_status = rpt.container_status

    # Always update in-memory status for REST endpoints
    camera_status.update(
        store_id=store_id,
        camera_id=camera_id,
        status=container_status,
        timestamp_ms=rpt.timestamp_ms,
    )

    if container_status == "running":
        await camera_status.mark_running(store_id, camera_id)

    elif container_status in ("exited", "dead", "not_found"):
        await camera_status.mark_stopped(store_id, camera_id)
        # Bridge crash to the scheduler so it can restart on the next tick
        await _mark_scheduler_stopped_by_physical_camera(store_id, camera_id)

    elif container_status == "restarting":
        # Docker is recovering — hold state, do not remove from _running_cameras (R6)
        logger.info("camera %s restarting — holding state", camera_id)

    logger.info(
        "CameraStatusReport  store=%s  camera=%s  status=%s",
        store_id, camera_id, container_status,
    )


async def _mark_scheduler_stopped_by_physical_camera(
    store_id: str, physical_camera_id: str
) -> None:
    """Look up camera_config_id from physical_camera_id and call scheduler.mark_stopped.

    The scheduler tracks _running_cameras by camera_config_id; this bridges the
    physical-camera-based crash report to the scheduler's key space so the
    scheduler can attempt a restart on the next tick.
    """
    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                _CAMERA_CONFIG_LOOKUP_SQL,
                {
                    "physical_camera_id": uuid.UUID(physical_camera_id),
                    "store_id":           uuid.UUID(store_id),
                },
            )
            row = result.fetchone()
            if row:
                camera_scheduler.mark_stopped(store_id, str(row.camera_config_id))
                logger.info(
                    "Crash bridged to scheduler  camera=%s  config=%s",
                    physical_camera_id, row.camera_config_id,
                )
    except Exception as exc:
        logger.warning(
            "Failed to bridge crash to scheduler  camera=%s: %s",
            physical_camera_id, exc,
        )


async def _writer(queue: asyncio.Queue, context) -> None:
    while True:
        msg = await queue.get()
        await context.write(msg)


async def _upsert_agent(
    store_id: str,
    agent_version: str | None = None,
    status: str = "online",
) -> bool:
    """Returns False if the store doesn't exist (FK violation); True on success."""
    from sqlalchemy.exc import IntegrityError

    now = datetime.now(timezone.utc)
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(
                text("""
                    INSERT INTO edge_agents (store_id, status, last_heartbeat_at, agent_version, updated_at)
                    VALUES (:store_id, :status, :now, :version, :now)
                    ON CONFLICT (store_id) DO UPDATE SET
                        status            = EXCLUDED.status,
                        last_heartbeat_at = EXCLUDED.last_heartbeat_at,
                        agent_version     = COALESCE(EXCLUDED.agent_version, edge_agents.agent_version),
                        updated_at        = EXCLUDED.updated_at
                """),
                {"store_id": uuid.UUID(store_id), "status": status, "now": now, "version": agent_version},
            )
            await session.commit()
        return True
    except IntegrityError:
        logger.warning(
            "edge_agents upsert: store not found, ignoring",
            extra={"store_id": store_id},
        )
        return False
