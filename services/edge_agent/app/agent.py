import asyncio
import logging
import os
import time

import grpc.aio

from services.edge_agent.app.grpc_generated.agent_pb2 import (
    AgentMessage,
    CameraStatusReport,
    Heartbeat,
)
from services.edge_agent.app.grpc_generated.agent_pb2_grpc import AgentServiceStub
from services.edge_agent.app import docker_manager

logger = logging.getLogger(__name__)

# Env vars for Docker integration — set at container start time.
# IEP1_IMAGE:     Docker image tag for the IEP1 ingestion container.
# DOCKER_NETWORK: Compose network name; verify with `docker network ls | grep retail`.
IEP1_IMAGE     = os.environ.get("IEP1_IMAGE",     "retailvision-iep1:latest")
DOCKER_NETWORK = os.environ.get("DOCKER_NETWORK", "retail-edge_default")

# Module-level outgoing queue. Not recreated on reconnect — queued commands
# from before a disconnect are replayed after reconnect.
_outgoing: asyncio.Queue = asyncio.Queue()

# Tracked cameras survive a gRPC disconnect/reconnect cycle.
_tracked_cameras: dict[str, str] = {}  # camera_id → store_id


async def run_agent(grpc_url: str, store_id: str, agent_version: str) -> None:
    backoff = 1
    while True:
        try:
            logger.info("Connecting to EEP", extra={"url": grpc_url})
            await _connect(grpc_url, store_id, agent_version)
            backoff = 1  # reset on clean disconnect
        except Exception as exc:
            logger.warning(
                "Connection failed, retrying",
                extra={"backoff": backoff, "error": str(exc)},
            )
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60)


async def _connect(grpc_url: str, store_id: str, agent_version: str) -> None:
    async with grpc.aio.insecure_channel(grpc_url) as channel:
        stub = AgentServiceStub(channel)
        hb_task = asyncio.create_task(_heartbeat_loop(store_id, agent_version))
        try:
            async for ctrl_msg in stub.Connect(_request_generator()):
                await _handle_control(ctrl_msg)
        finally:
            hb_task.cancel()
            try:
                await hb_task
            except asyncio.CancelledError:
                pass


async def _request_generator():
    while True:
        msg = await _outgoing.get()
        yield msg


async def _heartbeat_loop(store_id: str, agent_version: str) -> None:
    while True:
        await _outgoing.put(AgentMessage(
            heartbeat=Heartbeat(
                store_id=store_id,
                agent_version=agent_version,
                timestamp_ms=int(time.time() * 1000),
            )
        ))

        for camera_id, cam_store_id in list(_tracked_cameras.items()):
            status = docker_manager.get_status(cam_store_id, camera_id)
            await _outgoing.put(AgentMessage(
                camera_status=CameraStatusReport(
                    camera_id=camera_id,
                    container_status=status,
                    timestamp_ms=int(time.time() * 1000),
                )
            ))

        await asyncio.sleep(30)


async def _handle_control(ctrl_msg) -> None:
    loop = asyncio.get_running_loop()

    if ctrl_msg.HasField("start_camera"):
        cmd = ctrl_msg.start_camera
        logger.info("StartCamera received", extra={"camera_id": cmd.camera_id})
        await loop.run_in_executor(
            None, docker_manager.start_iep1, cmd, IEP1_IMAGE, DOCKER_NETWORK
        )
        _tracked_cameras[cmd.camera_id] = cmd.store_id

    elif ctrl_msg.HasField("stop_camera"):
        cmd = ctrl_msg.stop_camera
        logger.info("StopCamera received", extra={"camera_id": cmd.camera_id})
        await loop.run_in_executor(
            None, docker_manager.stop_iep1, cmd.store_id, cmd.camera_id
        )
        _tracked_cameras.pop(cmd.camera_id, None)
