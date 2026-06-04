"""Edge Agent — local orchestrator for the edge pipeline.

Startup sequence (R1):
  1. Ensure YOLO-service and OSNet-service containers running
  2. Wait for YOLO + OSNet grpc.health.v1 = SERVING
  3. Ensure IEP1-daemon container running
  4. Wait for IEP1 grpc.health.v1 = SERVING
  5. Rebuild _tracked_cameras from running Docker containers (R2)
  6. Re-add active cameras to IEP1 (R2)
  7. Connect gRPC stream to EEP

Per-camera lifecycle (R4/R5):
  StartCamera: start IEP2 → wait IEP2 SERVING → AddCamera to IEP1
  StopCamera:  RemoveCamera from IEP1 → stop IEP2
"""
import asyncio
import logging
import os
import random
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import grpc
import grpc.aio
from grpc_health.v1 import health_pb2, health_pb2_grpc

from services.edge_agent.app import docker_manager as dm
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

# ── Environment ────────────────────────────────────────────────────────────────
STORE_ID       = os.environ["STORE_ID"]
WINDOW_SECONDS = float(os.environ.get("WINDOW_SECONDS", "60"))

IEP1_CONTROL_SOCK = os.environ.get(
    "IEP1_CONTROL_SOCK", "unix:///tmp/iep1-sockets/iep1_control.sock"
)
IEP1_HEALTH_SOCK = os.environ.get(
    "IEP1_HEALTH_SOCK", "unix:///tmp/iep1-sockets/iep1_health.sock"
)
# TCP addresses for YOLO/OSNet health — containers share a Docker network
YOLO_HEALTH_SOCK  = os.environ.get("YOLO_HEALTH_SOCK",  "yolo-service:50052")
OSNET_HEALTH_SOCK = os.environ.get("OSNET_HEALTH_SOCK", "osnet-service:50053")

# IEP2 environment variables forwarded from Edge Agent env
LOCAL_REDIS_URL     = os.environ.get("LOCAL_REDIS_URL",     "redis://redis:6379/0")
SERVER_REDIS_URL    = os.environ.get("SERVER_REDIS_URL",    "")
DATABASE_URL_SERVER = os.environ.get("DATABASE_URL_SERVER", "")

# ── Module-level state ─────────────────────────────────────────────────────────

@dataclass
class CameraState:
    camera_id:      str
    store_id:       str
    iep2_running:   bool
    iep1_added:     bool
    # Populated from StartCamera commands; may be "" when rebuilt from Docker on startup.
    # _restore_active_cameras skips cameras with empty rtsp_url (no config to restore).
    rtsp_url:       str   = ""
    target_fps:     float = 0.0
    window_seconds: float = 0.0


_tracked_cameras:  dict[str, CameraState] = {}
_starting_cameras: set[str]               = set()
_outgoing:         asyncio.Queue          = asyncio.Queue()

# R6: all Docker SDK calls run in this executor — never on the asyncio thread
_docker_exec = ThreadPoolExecutor(max_workers=4, thread_name_prefix="edge-docker")

# ── Inference service descriptors (R10) ────────────────────────────────────────
_INFERENCE_SERVICES = [
    {
        "name":    "yolo-service",
        "image":   dm.YOLO_IMAGE,
        "volumes": {dm.IPC_SOCKETS_VOLUME: {"bind": "/tmp/sockets", "mode": "rw"}},
        "runtime": "nvidia",
    },
    {
        "name":    "osnet-service",
        "image":   dm.OSNET_IMAGE,
        "volumes": {dm.IPC_SOCKETS_VOLUME: {"bind": "/tmp/sockets", "mode": "rw"}},
        "runtime": "nvidia",
    },
]

_IEP1_DAEMON_VOLUMES = {
    dm.IEP1_SOCKETS_VOLUME: {"bind": "/tmp/iep1-sockets", "mode": "rw"},
    dm.FRAME_STORE_VOLUME:   {"bind": "/dev/shm/frames",  "mode": "rw"},
}
_IEP1_DAEMON_ENV = {
    "REDIS_URL":         LOCAL_REDIS_URL,
    "IEP1_CONTROL_SOCK": "unix:///tmp/iep1-sockets/iep1_control.sock",
    "IEP1_HEALTH_SOCK":  "unix:///tmp/iep1-sockets/iep1_health.sock",
    "TMPFS_FRAME_ROOT":  "/dev/shm/frames",
}


# ── Health helpers ─────────────────────────────────────────────────────────────

async def _wait_for_health(name: str, sock: str, timeout: int) -> None:
    """Poll grpc.health.v1 until SERVING or timeout (raises RuntimeError)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            async with grpc.aio.insecure_channel(sock) as ch:
                stub = health_pb2_grpc.HealthStub(ch)
                resp = await stub.Check(
                    health_pb2.HealthCheckRequest(service=""), timeout=2.0
                )
                if resp.status == health_pb2.HealthCheckResponse.SERVING:
                    logger.info("%s is SERVING", name)
                    return
        except Exception:
            pass
        await asyncio.sleep(2)
    raise RuntimeError(f"{name} did not become SERVING within {timeout}s")


async def _wait_for_iep2_health(camera_id: str, timeout: int = 30) -> None:
    sock = f"unix:///tmp/sockets/iep2_health_{camera_id}.sock"
    await _wait_for_health(f"iep2-{camera_id}", sock, timeout)


# ── Startup (R1) ──────────────────────────────────────────────────────────────

async def _startup() -> None:
    loop = asyncio.get_running_loop()

    # 1+2: inference services first
    for svc in _INFERENCE_SERVICES:
        await loop.run_in_executor(
            _docker_exec,
            dm.ensure_service_running,
            svc["name"], svc["image"], svc["volumes"],
            svc.get("env"), svc.get("runtime"),
        )

    await _wait_for_health("yolo",  YOLO_HEALTH_SOCK,  timeout=120)
    await _wait_for_health("osnet", OSNET_HEALTH_SOCK, timeout=120)

    # 3+4: IEP1 daemon
    await loop.run_in_executor(
        _docker_exec,
        dm.ensure_service_running,
        "iep1-daemon", dm.IEP1_IMAGE, _IEP1_DAEMON_VOLUMES,
        _IEP1_DAEMON_ENV, None,
    )
    await _wait_for_health("iep1", IEP1_HEALTH_SOCK, timeout=60)

    # 5+6: rebuild state and restore active cameras
    await _rebuild_tracked_cameras()
    await _restore_active_cameras()


# ── Startup rebuild (R2) ──────────────────────────────────────────────────────

async def _rebuild_tracked_cameras() -> None:
    """Scan running iep2_* containers and confirm against IEP1 GetStatus."""
    loop = asyncio.get_running_loop()
    _tracked_cameras.clear()

    running = await loop.run_in_executor(_docker_exec, dm.list_running_iep2_containers)
    for store_id, camera_id in running:
        _tracked_cameras[camera_id] = CameraState(
            camera_id=camera_id,
            store_id=store_id,
            iep2_running=True,
            iep1_added=False,
        )

    if not _tracked_cameras:
        logger.info("Rebuilt tracking: no IEP2 containers running")
        return

    # Confirm which cameras IEP1 already knows about
    try:
        async with grpc.aio.insecure_channel(IEP1_CONTROL_SOCK) as ch:
            stub = Iep1ControlStub(ch)
            status = await stub.GetStatus(Empty(), timeout=5.0)
            for cam in status.cameras:
                if cam.camera_id in _tracked_cameras:
                    _tracked_cameras[cam.camera_id].iep1_added = True
    except Exception as exc:
        logger.warning("GetStatus failed during startup rebuild: %s", exc)

    n_added = sum(1 for c in _tracked_cameras.values() if c.iep1_added)
    logger.info(
        "Rebuilt tracking: %d cameras  (iep1_confirmed: %d)",
        len(_tracked_cameras), n_added,
    )


async def _restore_active_cameras() -> None:
    """Re-add cameras to IEP1 that have IEP2 running but are missing from IEP1."""
    for cam in list(_tracked_cameras.values()):
        if cam.iep1_added:
            continue
        if not cam.rtsp_url:
            # Deviation from spec: CameraState has no rtsp_url when rebuilt
            # from Docker containers on startup — cannot restore without config.
            # EEP will re-send StartCamera after reconnect if needed.
            logger.warning(
                "Cannot restore camera %s to IEP1 — no RTSP config "
                "(Edge Agent restarted after IEP1 lost state; EEP will resync)",
                cam.camera_id,
            )
            continue
        await _add_camera_to_daemon(cam)


# ── IEP1 health watcher (R3) ──────────────────────────────────────────────────

async def _iep1_health_watcher() -> None:
    """Detect IEP1 restart via Watch stream and re-add all tracked cameras.

    Watch is event-driven (no polling). Outer loop reconnects if the stream
    is broken by a container restart.
    """
    was_serving = False
    while True:
        try:
            async with grpc.aio.insecure_channel(IEP1_HEALTH_SOCK) as ch:
                stub = health_pb2_grpc.HealthStub(ch)
                async for response in stub.Watch(
                    health_pb2.HealthCheckRequest(service="")
                ):
                    is_serving = (
                        response.status == health_pb2.HealthCheckResponse.SERVING
                    )
                    if is_serving and not was_serving:
                        logger.info(
                            "IEP1 recovered — restoring %d cameras",
                            len(_tracked_cameras),
                        )
                        for cam in list(_tracked_cameras.values()):
                            cam.iep1_added = False
                        await _restore_active_cameras()
                    was_serving = is_serving
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("IEP1 health Watch disconnected: %s — retrying in 5s", exc)
            was_serving = False  # treat reconnect as potential restart
            await asyncio.sleep(5)


# ── IEP1 gRPC helpers ─────────────────────────────────────────────────────────

async def _add_camera_to_daemon(cam: CameraState) -> None:
    try:
        async with grpc.aio.insecure_channel(IEP1_CONTROL_SOCK) as ch:
            stub = Iep1ControlStub(ch)
            resp = await stub.AddCamera(
                CameraConfig(
                    camera_id=cam.camera_id,
                    rtsp_url=cam.rtsp_url,
                    target_fps=cam.target_fps,
                    window_seconds=cam.window_seconds or WINDOW_SECONDS,
                    store_id=cam.store_id,
                ),
                timeout=5.0,
            )
            if resp.success:
                cam.iep1_added = True
                logger.info("AddCamera ok  camera=%s", cam.camera_id)
            else:
                logger.warning(
                    "AddCamera rejected  camera=%s  error=%s",
                    cam.camera_id, resp.error,
                )
    except Exception as exc:
        logger.warning("AddCamera RPC failed  camera=%s: %s", cam.camera_id, exc)


# ── IEP2 env builder ──────────────────────────────────────────────────────────

def _build_iep2_env(camera_id: str, store_id: str) -> dict:
    return {
        "CAMERA_ID":           camera_id,
        "STORE_ID":            store_id,
        "WINDOW_SECONDS":      str(WINDOW_SECONDS),
        "LOCAL_REDIS_URL":     LOCAL_REDIS_URL,
        "SERVER_REDIS_URL":    SERVER_REDIS_URL,
        "DATABASE_URL_SERVER": DATABASE_URL_SERVER,
    }


# ── Command handlers ───────────────────────────────────────────────────────────

async def _handle_start_camera(cmd) -> None:
    """R4: IEP2 must be SERVING before IEP1 begins publishing."""
    camera_id = cmd.camera_id
    store_id  = cmd.store_id

    # R8: reject commands for other stores
    if store_id != STORE_ID:
        logger.error(
            "StartCamera for wrong store %s (this device is %s) — ignoring",
            store_id, STORE_ID,
        )
        return

    # Dedup in-flight starts
    if camera_id in _starting_cameras:
        logger.warning("StartCamera for %s already in flight — ignoring", camera_id)
        return
    _starting_cameras.add(camera_id)

    try:
        loop = asyncio.get_running_loop()

        # Step 1: start IEP2 container (blocking Docker call in executor)
        env = _build_iep2_env(camera_id, store_id)
        await loop.run_in_executor(_docker_exec, dm.start_iep2, store_id, camera_id, env)

        # Step 2: wait for IEP2 health SERVING
        await _wait_for_iep2_health(camera_id, timeout=30)

        # Step 3: add camera to IEP1 daemon (IEP2 is ready to consume)
        cam = CameraState(
            camera_id=camera_id,
            store_id=store_id,
            iep2_running=True,
            iep1_added=False,
            rtsp_url=cmd.rtsp_url,
            target_fps=cmd.target_fps,
            window_seconds=cmd.window_seconds or WINDOW_SECONDS,
        )
        await _add_camera_to_daemon(cam)
        _tracked_cameras[camera_id] = cam

        await _send_immediate_status(camera_id)
        logger.info("StartCamera complete  camera=%s", camera_id)

    except Exception as exc:
        logger.error(
            "StartCamera failed  camera=%s: %s", camera_id, exc, exc_info=True
        )
    finally:
        _starting_cameras.discard(camera_id)


async def _handle_stop_camera(cmd) -> None:
    """R5: IEP1 stops publishing before IEP2 stops consuming."""
    camera_id = cmd.camera_id
    store_id  = cmd.store_id

    # R8: reject commands for other stores
    if store_id != STORE_ID:
        logger.error(
            "StopCamera for wrong store %s (this device is %s) — ignoring",
            store_id, STORE_ID,
        )
        return

    loop = asyncio.get_running_loop()
    cam  = _tracked_cameras.get(camera_id)

    # Step 1: remove from IEP1 (stops publishing immediately)
    if cam and cam.iep1_added:
        try:
            async with grpc.aio.insecure_channel(IEP1_CONTROL_SOCK) as ch:
                stub = Iep1ControlStub(ch)
                await stub.RemoveCamera(
                    RemoveCameraRequest(camera_id=camera_id), timeout=5.0
                )
            logger.info("RemoveCamera ok  camera=%s", camera_id)
        except Exception as exc:
            logger.warning("RemoveCamera failed  camera=%s: %s", camera_id, exc)

    # Step 2: stop IEP2 container (drains remaining manifests then exits)
    effective_store_id = cam.store_id if cam else store_id
    await loop.run_in_executor(
        _docker_exec, dm.stop_iep2, effective_store_id, camera_id
    )
    _tracked_cameras.pop(camera_id, None)

    await _send_immediate_status(camera_id)
    logger.info("StopCamera complete  camera=%s", camera_id)


async def _handle_control(ctrl_msg) -> None:
    # Dispatch as tasks so slow Docker operations don't block the EEP stream reader
    if ctrl_msg.HasField("start_camera"):
        logger.info("StartCamera received  camera=%s", ctrl_msg.start_camera.camera_id)
        asyncio.create_task(_handle_start_camera(ctrl_msg.start_camera))
    elif ctrl_msg.HasField("stop_camera"):
        logger.info("StopCamera received  camera=%s", ctrl_msg.stop_camera.camera_id)
        asyncio.create_task(_handle_stop_camera(ctrl_msg.stop_camera))


# ── Status reporting ───────────────────────────────────────────────────────────

async def _send_immediate_status(camera_id: str) -> None:
    """Push a CameraStatusReport into the outgoing queue immediately."""
    loop = asyncio.get_running_loop()
    cam  = _tracked_cameras.get(camera_id)
    if cam:
        name   = dm.iep2_container_name(cam.store_id, camera_id)
        status = await loop.run_in_executor(_docker_exec, dm.get_container_status, name)
    else:
        status = "not_found"
    await _outgoing.put(AgentMessage(
        camera_status=CameraStatusReport(
            camera_id=camera_id,
            container_status=status,
            timestamp_ms=int(time.time() * 1000),
        )
    ))


async def _heartbeat_loop(store_id: str, agent_version: str) -> None:
    loop = asyncio.get_running_loop()
    while True:
        await _outgoing.put(AgentMessage(
            heartbeat=Heartbeat(
                store_id=store_id,
                agent_version=agent_version,
                timestamp_ms=int(time.time() * 1000),
            )
        ))
        for camera_id, cam in list(_tracked_cameras.items()):
            name   = dm.iep2_container_name(cam.store_id, camera_id)
            status = await loop.run_in_executor(
                _docker_exec, dm.get_container_status, name
            )
            await _outgoing.put(AgentMessage(
                camera_status=CameraStatusReport(
                    camera_id=camera_id,
                    container_status=status,
                    timestamp_ms=int(time.time() * 1000),
                )
            ))
        await asyncio.sleep(30)


async def _request_generator():
    while True:
        msg = await _outgoing.get()
        yield msg


# ── EEP connection ─────────────────────────────────────────────────────────────

async def _connect_to_eep(grpc_url: str, store_id: str, agent_version: str) -> None:
    async with grpc.aio.insecure_channel(grpc_url) as channel:
        stub = AgentServiceStub(channel)
        hb_task    = asyncio.create_task(_heartbeat_loop(store_id, agent_version))
        watch_task = asyncio.create_task(_iep1_health_watcher())
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


# ── Entry point ────────────────────────────────────────────────────────────────

async def run_agent(grpc_url: str, store_id: str, agent_version: str) -> None:
    await _startup()

    backoff = 1
    while True:
        try:
            logger.info("Connecting to EEP  url=%s", grpc_url)
            await _connect_to_eep(grpc_url, store_id, agent_version)
            backoff = 1
        except grpc.aio.AioRpcError as exc:
            logger.warning("gRPC error code=%s — reconnecting", exc.code())
            jitter = random.uniform(0, backoff * 0.3)
            await asyncio.sleep(backoff + jitter)
            backoff = min(backoff * 2, 60)
        except Exception as exc:
            logger.error("Unexpected error: %s", exc, exc_info=True)
            jitter = random.uniform(0, backoff * 0.3)
            await asyncio.sleep(backoff + jitter)
            backoff = min(backoff * 2, 60)
