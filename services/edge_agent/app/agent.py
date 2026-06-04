import asyncio
import logging
import os
import time

import grpc
import grpc.aio
from grpc_health.v1 import health_pb2, health_pb2_grpc

from services.edge_agent.app.grpc_generated.agent_pb2 import (
    AgentMessage,
    CameraStatusReport,
    Heartbeat,
)
from services.edge_agent.app.grpc_generated.agent_pb2_grpc import AgentServiceStub
from services.edge_agent.app.grpc_generated.iep1_control_pb2 import (
    CameraConfig,
    Empty,
    RemoveCameraRequest,
)
from services.edge_agent.app.grpc_generated.iep1_control_pb2_grpc import Iep1ControlStub

logger = logging.getLogger(__name__)

IEP1_CONTROL_SOCK = os.environ.get(
    "IEP1_CONTROL_SOCK", "unix:///tmp/iep1-sockets/iep1_control.sock"
)
IEP1_HEALTH_SOCK  = os.environ.get(
    "IEP1_HEALTH_SOCK", "unix:///tmp/iep1-sockets/iep1_health.sock"
)

_outgoing: asyncio.Queue = asyncio.Queue()

# camera_id → StartCamera proto message (preserved across reconnects for re-add on daemon restart)
_tracked_cameras: dict[str, object] = {}


async def run_agent(grpc_url: str, store_id: str, agent_version: str) -> None:
    backoff = 1
    while True:
        try:
            logger.info("Connecting to EEP", extra={"url": grpc_url})
            await _connect(grpc_url, store_id, agent_version)
            backoff = 1
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
        hb_task     = asyncio.create_task(_heartbeat_loop(store_id, agent_version))
        watch_task  = asyncio.create_task(_daemon_health_watcher())
        try:
            async for ctrl_msg in stub.Connect(_request_generator()):
                await _handle_control(ctrl_msg)
        finally:
            for task in (hb_task, watch_task):
                task.cancel()
                try:
                    await task
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

        for camera_id, cmd in list(_tracked_cameras.items()):
            status = await _get_camera_status(camera_id)
            await _outgoing.put(AgentMessage(
                camera_status=CameraStatusReport(
                    camera_id=camera_id,
                    container_status=status,
                    timestamp_ms=int(time.time() * 1000),
                )
            ))

        await asyncio.sleep(30)


async def _get_camera_status(camera_id: str) -> str:
    """Query IEP1 daemon GetStatus and return the status string for this camera."""
    try:
        async with grpc.aio.insecure_channel(IEP1_CONTROL_SOCK) as ch:
            stub = Iep1ControlStub(ch)
            resp = await stub.GetStatus(Empty(), timeout=3.0)
            for cam in resp.cameras:
                if cam.camera_id == camera_id:
                    return cam.status
        return "stopped"
    except Exception:
        return "stopped"


async def _daemon_health_watcher() -> None:
    """R10: detect IEP1 daemon restart and re-add all tracked cameras."""
    was_serving = False
    while True:
        await asyncio.sleep(10)
        now_serving = await _is_daemon_serving()
        if now_serving and not was_serving and _tracked_cameras:
            logger.info("IEP1 daemon restarted — re-adding %d cameras", len(_tracked_cameras))
            for cmd in list(_tracked_cameras.values()):
                await _add_camera_to_daemon(cmd)
        was_serving = now_serving


async def _is_daemon_serving() -> bool:
    try:
        async with grpc.aio.insecure_channel(IEP1_HEALTH_SOCK) as ch:
            stub = health_pb2_grpc.HealthStub(ch)
            resp = await stub.Check(
                health_pb2.HealthCheckRequest(service=""), timeout=2.0
            )
            return resp.status == health_pb2.HealthCheckResponse.SERVING
    except Exception:
        return False


async def _add_camera_to_daemon(cmd) -> None:
    try:
        async with grpc.aio.insecure_channel(IEP1_CONTROL_SOCK) as ch:
            stub = Iep1ControlStub(ch)
            cfg  = CameraConfig(
                camera_id=cmd.camera_id,
                rtsp_url=cmd.rtsp_url,
                target_fps=cmd.target_fps,
                window_seconds=cmd.window_seconds,
                store_id=cmd.store_id,
            )
            resp = await stub.AddCamera(cfg, timeout=5.0)
            if not resp.success:
                logger.warning(
                    "AddCamera failed camera=%s error=%s", cmd.camera_id, resp.error
                )
    except Exception as exc:
        logger.warning("AddCamera RPC failed camera=%s: %s", cmd.camera_id, exc)


async def _remove_camera_from_daemon(store_id: str, camera_id: str) -> None:
    try:
        async with grpc.aio.insecure_channel(IEP1_CONTROL_SOCK) as ch:
            stub = Iep1ControlStub(ch)
            await stub.RemoveCamera(
                RemoveCameraRequest(camera_id=camera_id), timeout=5.0
            )
    except Exception as exc:
        logger.warning("RemoveCamera RPC failed camera=%s: %s", camera_id, exc)


async def _handle_control(ctrl_msg) -> None:
    if ctrl_msg.HasField("start_camera"):
        cmd = ctrl_msg.start_camera
        logger.info("StartCamera received", extra={"camera_id": cmd.camera_id})
        await _add_camera_to_daemon(cmd)
        _tracked_cameras[cmd.camera_id] = cmd

    elif ctrl_msg.HasField("stop_camera"):
        cmd = ctrl_msg.stop_camera
        logger.info("StopCamera received", extra={"camera_id": cmd.camera_id})
        await _remove_camera_from_daemon(cmd.store_id, cmd.camera_id)
        _tracked_cameras.pop(cmd.camera_id, None)
