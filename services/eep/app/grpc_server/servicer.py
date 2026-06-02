import asyncio
import logging
import uuid
from datetime import datetime, timezone

import grpc
from sqlalchemy import text

from app.core.database import AsyncSessionLocal
from app.grpc_generated import agent_pb2, agent_pb2_grpc
from app.grpc_server import camera_status, registry

logger = logging.getLogger(__name__)


class AgentServiceServicer(agent_pb2_grpc.AgentServiceServicer):

    async def Connect(self, request_iterator, context):
        store_id = None
        try:
            first = await request_iterator.__anext__()
            if not first.HasField("heartbeat"):
                await context.abort(
                    grpc.StatusCode.INVALID_ARGUMENT,
                    "First message must be Heartbeat",
                )
                return

            store_id = first.heartbeat.store_id
            agent_version = first.heartbeat.agent_version
            logger.info("Agent connected", extra={"store_id": store_id, "version": agent_version})

            queue = await registry.register(store_id)
            await _upsert_agent(store_id, agent_version, status="online")

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
                await _upsert_agent(store_id, status="offline")
                logger.info("Agent disconnected", extra={"store_id": store_id})


async def _reader(request_iterator, store_id: str) -> None:
    async for msg in request_iterator:
        if msg.HasField("heartbeat"):
            await _upsert_agent(store_id, msg.heartbeat.agent_version, status="online")
        elif msg.HasField("camera_status"):
            rpt = msg.camera_status
            logger.info(
                "Camera status report",
                extra={
                    "store_id": store_id,
                    "camera_id": rpt.camera_id,
                    "status": rpt.container_status,
                },
            )
            camera_status.update(
                store_id=store_id,
                camera_id=rpt.camera_id,
                status=rpt.container_status,
                timestamp_ms=rpt.timestamp_ms,
            )


async def _writer(queue: asyncio.Queue, context) -> None:
    while True:
        msg = await queue.get()
        await context.write(msg)


async def _upsert_agent(
    store_id: str,
    agent_version: str | None = None,
    status: str = "online",
) -> None:
    now = datetime.now(timezone.utc)
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
