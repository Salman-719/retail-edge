"""Edge Agent — thin gRPC relay: translates EEP commands into k3s/Docker operations.

Startup sequence:
  1. Init backend: try k3s (kubeconfig); fall back to Docker if k3s unavailable
  2. Wait for YOLO + ReID grpc.health.v1 = SERVING
  3. Wait for IEP1 grpc.health.v1 = SERVING
  4. Restore active cameras from backend (k3s Deployments or Docker containers)
  5. Connect gRPC stream to EEP

Per-camera lifecycle:
  StartCamera: apply ConfigMap + Deployment → wait IEP2 SERVING → AddCamera to IEP1
  StopCamera:  cancel health watcher → RemoveCamera from IEP1 → delete backend resources

Backend (k3s_manager or docker_manager) is the source of truth for container state.
"""
import asyncio
import logging
import os
import random
import time
from concurrent.futures import ThreadPoolExecutor

import grpc
import grpc.aio
from grpc_health.v1 import health_pb2, health_pb2_grpc

from services.edge_agent.app import docker_manager as dm
from services.edge_agent.app import k8s_manager as km
from services.edge_agent.app.grpc_generated.agent_pb2 import (
    AgentMessage,
    CameraStatusReport,
    Heartbeat,
)
from services.edge_agent.app.grpc_generated.agent_pb2_grpc import AgentServiceStub
from services.edge_agent.app.grpc_generated.iep1_control_pb2 import (
    CameraConfig,
    RemoveCameraRequest,
)
from services.edge_agent.app.grpc_generated.iep1_control_pb2_grpc import Iep1ControlStub

logger = logging.getLogger(__name__)

# ── Environment ────────────────────────────────────────────────────────────────
STORE_ID       = os.environ["STORE_ID"]
WINDOW_SECONDS = float(os.environ.get("WINDOW_SECONDS", "60"))

# Edge Agent runs as a systemd service on the host and accesses IEP1 via the
# hostPath volume (/dev/shm/sockets), not the pod-internal /tmp/sockets mount.
IEP1_CONTROL_SOCK = os.environ.get(
    "IEP1_CONTROL_SOCK", "unix:///dev/shm/sockets/iep1_control.sock"
)
IEP1_HEALTH_SOCK = os.environ.get(
    "IEP1_HEALTH_SOCK", "unix:///dev/shm/sockets/iep1_health.sock"
)
# Inference services expose their gRPC health via hostPort on the node.
YOLO_HEALTH_SOCK  = os.environ.get("YOLO_HEALTH_SOCK",  "localhost:50052")
REID_HEALTH_SOCK = os.environ.get("REID_HEALTH_SOCK", "localhost:50053")

LOCAL_REDIS_URL      = os.environ.get("LOCAL_REDIS_URL",     "redis://localhost:6379/0")
SERVER_REDIS_URL     = os.environ.get("SERVER_REDIS_URL",    "")
DATABASE_URL_SERVER  = os.environ.get("DATABASE_URL_SERVER", "")
HEARTBEAT_INTERVAL_S = int(os.environ.get("HEARTBEAT_INTERVAL_S", "30"))

# TLS — CA cert used to verify EEP server certificate
GRPC_CA_CERT_PATH = os.environ.get("GRPC_CA_CERT_PATH", "/etc/retailvision/certs/ca.crt")
# Shared secret sent as x-agent-token metadata on every RPC
AGENT_SECRET = os.environ.get("AGENT_SECRET", "")

# Host-side path for k3s hostPath volume (/dev/shm/sockets → /tmp/sockets in pods).
IPC_SOCKETS_HOST_PATH = os.environ.get("IPC_SOCKETS_HOST_PATH", "/dev/shm/sockets")

# ── Module-level state ─────────────────────────────────────────────────────────

_starting_cameras: set[str]                = set()
# R7: bounded — status reports dropped (not stalled) if the stream is reconnecting
_outgoing:         asyncio.Queue           = asyncio.Queue(maxsize=200)
# One Watch task per active camera
_health_watchers:  dict[str, asyncio.Task] = {}

# Active backend module — set in _startup() to km (k3s) or dm (Docker)
_mgr = km

# Backend API calls run in this executor — never on the asyncio thread
_exec = ThreadPoolExecutor(max_workers=4, thread_name_prefix="edge-mgr")


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


async def _wait_for_iep2_health(camera_id: str, timeout: int = 60) -> None:
    sock = f"unix://{IPC_SOCKETS_HOST_PATH}/iep2_health_{camera_id}.sock"
    await _wait_for_health(f"iep2-{camera_id}", sock, timeout)


# ── Startup ────────────────────────────────────────────────────────────────────

async def _startup() -> None:
    global _mgr
    loop = asyncio.get_running_loop()

    # Try k3s first; fall back to Docker if kubeconfig unavailable (production-local mode)
    await loop.run_in_executor(_exec, km.init_k8s_clients)
    if km.is_available():
        _mgr = km
        logger.info("Edge Agent backend: k3s (Kubernetes)")
    else:
        await loop.run_in_executor(_exec, dm.init_k8s_clients)
        _mgr = dm
        logger.info("Edge Agent backend: Docker (production-local mode)")

    # Wait for inference services
    await _wait_for_health("yolo",  YOLO_HEALTH_SOCK,  timeout=120)
    await _wait_for_health("reid", REID_HEALTH_SOCK, timeout=120)

    # Wait for IEP1 daemon (unix socket via hostPath / volume mount)
    await _wait_for_health("iep1", IEP1_HEALTH_SOCK, timeout=60)

    # Re-add cameras that survived this Edge Agent restart
    await _restore_active_cameras()


# ── Startup restore ────────────────────────────────────────────────────────────

async def _restore_active_cameras() -> None:
    """Re-add all active IEP2 cameras to IEP1 by reading k3s Deployments + ConfigMaps.

    RTSP_URL and TARGET_FPS are persisted in each camera's ConfigMap by
    _handle_start_camera, so restart recovery no longer requires EEP resync.
    Cameras whose ConfigMap lacks RTSP_URL are skipped with a warning.
    """
    loop = asyncio.get_running_loop()
    deployments = await loop.run_in_executor(_exec, _mgr.list_active_iep2_deployments)

    restored = 0
    for data in deployments:
        camera_id = data.get("camera_id", "")
        if not camera_id:
            continue

        rtsp_url = data.get("RTSP_URL", "")
        if not rtsp_url:
            logger.warning(
                "Cannot restore camera %s to IEP1 — no RTSP_URL in ConfigMap "
                "(EEP will resync if needed)",
                camera_id,
            )
            continue

        store_id = data.get("STORE_ID", STORE_ID)
        try:
            target_fps     = float(data.get("TARGET_FPS", "0"))
            window_seconds = float(data.get("WINDOW_SECONDS", str(WINDOW_SECONDS)))
        except ValueError:
            target_fps, window_seconds = 0.0, WINDOW_SECONDS

        await _add_camera_to_iep1(camera_id, store_id, rtsp_url, target_fps, window_seconds)

        if camera_id not in _health_watchers:
            _health_watchers[camera_id] = asyncio.create_task(
                _watch_iep2_health(camera_id),
                name=f"iep2-watch-{camera_id}",
            )
        restored += 1

    logger.info("Restored %d / %d cameras from backend", restored, len(deployments))


# ── IEP1 health watcher ────────────────────────────────────────────────────────

async def _iep1_health_watcher() -> None:
    """Detect IEP1 restart via Watch stream and re-add all active cameras.

    On SERVING→NOT_SERVING→SERVING transition, IEP1 has lost all camera state.
    _restore_active_cameras reads k3s to rebuild the full set.
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
                            len(_health_watchers),
                        )
                        await _restore_active_cameras()
                    was_serving = is_serving
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("IEP1 health Watch disconnected: %s — retrying in 5s", exc)
            was_serving = False
            await asyncio.sleep(5)


# ── IEP1 gRPC helper ───────────────────────────────────────────────────────────

async def _add_camera_to_iep1(
    camera_id: str,
    store_id: str,
    rtsp_url: str,
    target_fps: float,
    window_seconds: float,
) -> bool:
    try:
        async with grpc.aio.insecure_channel(IEP1_CONTROL_SOCK) as ch:
            stub = Iep1ControlStub(ch)
            resp = await stub.AddCamera(
                CameraConfig(
                    camera_id=camera_id,
                    rtsp_url=rtsp_url,
                    target_fps=target_fps,
                    window_seconds=window_seconds or WINDOW_SECONDS,
                    store_id=store_id,
                ),
                timeout=5.0,
            )
            if resp.success:
                logger.info("AddCamera ok  camera=%s", camera_id)
            else:
                logger.warning(
                    "AddCamera rejected  camera=%s  error=%s", camera_id, resp.error
                )
            return resp.success
    except Exception as exc:
        logger.warning("AddCamera RPC failed  camera=%s: %s", camera_id, exc)
        return False


# ── ConfigMap data builder ─────────────────────────────────────────────────────

def _build_configmap_data(
    camera_id: str,
    store_id: str,
    rtsp_url: str,
    target_fps: float,
    camera_config_id: str = "",
) -> dict:
    """Build the ConfigMap payload for an IEP2 pod.

    RTSP_URL and TARGET_FPS are stored for Edge Agent restart recovery.
    IEP2 does not use them directly.
    """
    return {
        "CAMERA_ID":           camera_id,
        "STORE_ID":            store_id,
        "WINDOW_SECONDS":      str(WINDOW_SECONDS),
        "LOCAL_REDIS_URL":     LOCAL_REDIS_URL,
        "SERVER_REDIS_URL":    SERVER_REDIS_URL,
        "DATABASE_URL_SERVER": DATABASE_URL_SERVER,
        "RTSP_URL":            rtsp_url,
        "TARGET_FPS":          str(target_fps),
        "CAMERA_CONFIG_ID":    camera_config_id,
    }


# ── IEP2 health watcher ────────────────────────────────────────────────────────

async def _watch_iep2_health(camera_id: str) -> None:
    """Open a Watch stream to IEP2's grpc.health.v1 service.

    Exits only on CancelledError (task cancelled by _handle_stop_camera).
    Sends an immediate status report on NOT_SERVING or stream failure.
    """
    sock = f"unix://{IPC_SOCKETS_HOST_PATH}/iep2_health_{camera_id}.sock"
    while True:
        try:
            async with grpc.aio.insecure_channel(sock) as ch:
                stub = health_pb2_grpc.HealthStub(ch)
                async for response in stub.Watch(
                    health_pb2.HealthCheckRequest(service="")
                ):
                    if response.status != health_pb2.HealthCheckResponse.SERVING:
                        await _send_immediate_status(camera_id)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.debug("IEP2 Watch stream failed  camera=%s: %s", camera_id, exc)
            await _send_immediate_status(camera_id)
            await asyncio.sleep(5)


# ── Command handlers ───────────────────────────────────────────────────────────

async def _handle_start_camera(cmd) -> None:
    """Apply ConfigMap + Deployment to k3s, wait IEP2 SERVING, then add to IEP1."""
    camera_id = cmd.camera_id
    store_id  = cmd.store_id

    if store_id != STORE_ID:
        logger.error(
            "StartCamera for wrong store %s (this device is %s) — ignoring",
            store_id, STORE_ID,
        )
        return

    if camera_id in _starting_cameras:
        logger.warning("StartCamera for %s already in flight — ignoring", camera_id)
        return
    _starting_cameras.add(camera_id)

    try:
        loop = asyncio.get_running_loop()

        # Step 1: write ConfigMap and Deployment to backend (k3s or Docker)
        cm_data = _build_configmap_data(
            camera_id, store_id, cmd.rtsp_url, cmd.target_fps,
            camera_config_id=cmd.camera_config_id,
        )
        await loop.run_in_executor(_exec, _mgr.apply_camera_configmap, camera_id, cm_data)
        await loop.run_in_executor(_exec, _mgr.apply_iep2_deployment, camera_id)

        # Step 2: wait for IEP2 to report SERVING on its unix health socket
        await _wait_for_iep2_health(camera_id, timeout=60)

        # Step 3: add to IEP1 — IEP2 is now ready to consume from the Redis stream
        window_seconds = cmd.window_seconds or WINDOW_SECONDS
        await _add_camera_to_iep1(
            camera_id, store_id, cmd.rtsp_url, cmd.target_fps, window_seconds
        )

        # Step 4: start per-camera health watcher (replace any stale task)
        if camera_id in _health_watchers:
            _health_watchers[camera_id].cancel()
            await asyncio.gather(_health_watchers[camera_id], return_exceptions=True)
        _health_watchers[camera_id] = asyncio.create_task(
            _watch_iep2_health(camera_id),
            name=f"iep2-watch-{camera_id}",
        )

        await _send_immediate_status(camera_id)
        logger.info("StartCamera complete  camera=%s", camera_id)

    except Exception as exc:
        logger.error("StartCamera failed  camera=%s: %s", camera_id, exc, exc_info=True)
    finally:
        _starting_cameras.discard(camera_id)


async def _handle_stop_camera(cmd) -> None:
    """Cancel watcher, remove from IEP1, then delete k3s Deployment + ConfigMap."""
    camera_id = cmd.camera_id
    store_id  = cmd.store_id

    if store_id != STORE_ID:
        logger.error(
            "StopCamera for wrong store %s (this device is %s) — ignoring",
            store_id, STORE_ID,
        )
        return

    # Cancel health watcher before stopping (avoids spurious status reports)
    watcher = _health_watchers.pop(camera_id, None)
    if watcher:
        watcher.cancel()
        await asyncio.gather(watcher, return_exceptions=True)

    loop = asyncio.get_running_loop()

    # Step 1: remove from IEP1 (stops publishing immediately)
    try:
        async with grpc.aio.insecure_channel(IEP1_CONTROL_SOCK) as ch:
            stub = Iep1ControlStub(ch)
            await stub.RemoveCamera(
                RemoveCameraRequest(camera_id=camera_id), timeout=5.0
            )
        logger.info("RemoveCamera ok  camera=%s", camera_id)
    except Exception as exc:
        logger.warning("RemoveCamera failed  camera=%s: %s", camera_id, exc)

    # Step 2: delete backend Deployment + ConfigMap (k3s or Docker)
    await loop.run_in_executor(_exec, _mgr.delete_iep2, camera_id)

    await _send_immediate_status(camera_id)
    logger.info("StopCamera complete  camera=%s", camera_id)


async def _handle_control(ctrl_msg) -> None:
    # Dispatch as tasks so K8s operations don't block the EEP stream reader
    if ctrl_msg.HasField("start_camera"):
        logger.info("StartCamera received  camera=%s", ctrl_msg.start_camera.camera_id)
        asyncio.create_task(_handle_start_camera(ctrl_msg.start_camera))
    elif ctrl_msg.HasField("stop_camera"):
        logger.info("StopCamera received  camera=%s", ctrl_msg.stop_camera.camera_id)
        asyncio.create_task(_handle_stop_camera(ctrl_msg.stop_camera))


# ── Status reporting ───────────────────────────────────────────────────────────

def _enqueue_status(msg: AgentMessage) -> None:
    """Non-blocking enqueue. Drops and warns if queue is full (R7)."""
    try:
        _outgoing.put_nowait(msg)
    except asyncio.QueueFull:
        camera_id = msg.camera_status.camera_id if msg.HasField("camera_status") else "?"
        logger.warning(
            "Outgoing queue full — dropping status report  camera=%s", camera_id
        )


async def _send_immediate_status(camera_id: str) -> None:
    """Query backend container status and enqueue a CameraStatusReport immediately."""
    loop   = asyncio.get_running_loop()
    status = await loop.run_in_executor(_exec, _mgr.get_camera_k8s_status, camera_id)
    _enqueue_status(AgentMessage(
        camera_status=CameraStatusReport(
            camera_id=camera_id,
            container_status=status,
            timestamp_ms=int(time.time() * 1000),
        )
    ))


async def _heartbeat_loop(store_id: str, agent_version: str) -> None:
    """Heartbeat + per-camera K8s status sweep every HEARTBEAT_INTERVAL_S."""
    loop = asyncio.get_running_loop()
    while True:
        try:
            _outgoing.put_nowait(AgentMessage(
                heartbeat=Heartbeat(
                    store_id=store_id,
                    agent_version=agent_version,
                    timestamp_ms=int(time.time() * 1000),
                )
            ))
        except asyncio.QueueFull:
            logger.warning("Outgoing queue full — dropping heartbeat")

        # Query backend for current camera list (source of truth)
        active = await loop.run_in_executor(_exec, _mgr.get_active_camera_ids)
        for camera_id in active:
            status = await loop.run_in_executor(
                _exec, _mgr.get_camera_k8s_status, camera_id
            )
            _enqueue_status(AgentMessage(
                camera_status=CameraStatusReport(
                    camera_id=camera_id,
                    container_status=status,
                    timestamp_ms=int(time.time() * 1000),
                )
            ))
        await asyncio.sleep(HEARTBEAT_INTERVAL_S)


async def _request_generator():
    while True:
        msg = await _outgoing.get()
        yield msg


# ── EEP connection ─────────────────────────────────────────────────────────────

def _load_channel_credentials() -> grpc.ChannelCredentials | None:
    """Load CA cert for TLS. Returns None in dev mode (cert file absent or unset)."""
    import os as _os
    if not GRPC_CA_CERT_PATH or not _os.path.exists(GRPC_CA_CERT_PATH):
        return None
    with open(GRPC_CA_CERT_PATH, "rb") as f:
        ca_cert = f.read()
    return grpc.ssl_channel_credentials(root_certificates=ca_cert)


_CHANNEL_OPTIONS = [
    ("grpc.keepalive_time_ms",              20000),
    ("grpc.keepalive_timeout_ms",           10000),
    ("grpc.keepalive_permit_without_calls",     1),
    ("grpc.http2.max_pings_without_data",       0),
]


async def _connect_to_eep(grpc_url: str, store_id: str, agent_version: str) -> None:
    credentials = _load_channel_credentials()
    if credentials:
        channel_ctx = grpc.aio.secure_channel(grpc_url, credentials, options=_CHANNEL_OPTIONS)
    else:
        logger.warning(
            "gRPC TLS disabled — GRPC_CA_CERT_PATH=%s not found (dev mode)",
            GRPC_CA_CERT_PATH,
        )
        channel_ctx = grpc.aio.insecure_channel(grpc_url, options=_CHANNEL_OPTIONS)

    async with channel_ctx as channel:
        stub     = AgentServiceStub(channel)
        metadata = (("x-agent-token", AGENT_SECRET),) if AGENT_SECRET else ()
        hb_task  = asyncio.create_task(_heartbeat_loop(store_id, agent_version))
        wt_task  = asyncio.create_task(_iep1_health_watcher())
        try:
            async for ctrl_msg in stub.Connect(_request_generator(), metadata=metadata):
                await _handle_control(ctrl_msg)
        finally:
            for task in (hb_task, wt_task):
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
