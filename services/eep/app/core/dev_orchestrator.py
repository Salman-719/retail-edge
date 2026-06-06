"""DEV-ONLY pipeline orchestrator for end-to-end IEP1→IEP2→IEP3 testing.

Used exclusively by the DEBUG_MODE dev-pipeline router. In production, IEP2 is
managed by the Edge Agent via k3s and cameras are started over the gRPC control
stream — this module is never imported there.

In dev there is no k3s, so this orchestrator:
  - calls IEP1.AddCamera / RemoveCamera directly over the IEP1 control unix
    socket (mounted into EEP via the dev compose override), and
  - spawns one IEP2 container per camera on the host docker.sock.

All functions are synchronous/blocking — call them from a thread executor.
"""
import logging
import os

logger = logging.getLogger(__name__)

# ── IEP1 control socket (mounted into EEP in docker-compose.dev.yml) ────────────
IEP1_CONTROL_SOCK = os.environ.get(
    "IEP1_CONTROL_SOCK", "unix:///tmp/iep1-sockets/iep1_control.sock"
)

# ── IEP2 container spawn parameters ─────────────────────────────────────────────
IEP2_IMAGE         = os.environ.get("IEP2_IMAGE", "retail-edge-iep2_vision:latest")
DOCKER_NETWORK     = os.environ.get("DOCKER_NETWORK", "retail-edge_default")
IPC_SOCKETS_VOLUME = os.environ.get("IPC_SOCKETS_VOLUME", "retail-edge_ipc-sockets")
FRAME_STORE_VOLUME = os.environ.get("FRAME_STORE_VOLUME", "retail-edge_frame-store")
LOCAL_REDIS_URL    = os.environ.get("LOCAL_REDIS_URL", "redis://redis:6379/0")
SERVER_REDIS_URL   = os.environ.get("SERVER_REDIS_URL", "redis://redis:6379/0")
LIVE_EMBED_FRAME   = os.environ.get("LIVE_EMBED_FRAME", "true")


def iep2_container_name(store_id: str, camera_id: str) -> str:
    return f"iep2_dev_{camera_id}"


# ── IEP1 control (gRPC over unix socket) ────────────────────────────────────────

def _iep1_channel():
    import grpc
    return grpc.insecure_channel(IEP1_CONTROL_SOCK)


def iep1_add_camera(
    camera_id: str,
    rtsp_url: str,
    store_id: str,
    target_fps: float,
    window_seconds: float,
) -> tuple[bool, str]:
    """Call IEP1.AddCamera. Returns (success, error_message)."""
    from app.grpc_generated import iep1_control_pb2 as pb2
    ch = _iep1_channel()
    add = ch.unary_unary(
        "/retailvision.iep1.v1.Iep1Control/AddCamera",
        request_serializer=pb2.CameraConfig.SerializeToString,
        response_deserializer=pb2.AddCameraResponse.FromString,
    )
    resp = add(
        pb2.CameraConfig(
            camera_id=camera_id,
            rtsp_url=rtsp_url,
            target_fps=target_fps,
            window_seconds=window_seconds,
            store_id=store_id,
        ),
        timeout=10.0,
    )
    return bool(resp.success), getattr(resp, "error", "") or ""


def iep1_remove_camera(camera_id: str) -> bool:
    from app.grpc_generated import iep1_control_pb2 as pb2
    ch = _iep1_channel()
    rm = ch.unary_unary(
        "/retailvision.iep1.v1.Iep1Control/RemoveCamera",
        request_serializer=pb2.RemoveCameraRequest.SerializeToString,
        response_deserializer=pb2.RemoveCameraResponse.FromString,
    )
    try:
        resp = rm(pb2.RemoveCameraRequest(camera_id=camera_id), timeout=10.0)
        return bool(resp.success)
    except Exception as exc:
        logger.warning("IEP1 RemoveCamera failed camera=%s: %s", camera_id, exc)
        return False


# ── IEP2 container lifecycle (host docker.sock) ─────────────────────────────────

def _docker_client():
    import docker
    return docker.from_env()


def start_iep2(
    store_id: str,
    camera_id: str,
    camera_config_id: str,
    database_url_server: str,
    window_seconds: float,
) -> str:
    """Spawn (or replace) the IEP2 container for one camera. Returns container name."""
    import docker

    name   = iep2_container_name(store_id, camera_id)
    client = _docker_client()

    try:
        old = client.containers.get(name)
        old.remove(force=True)
        logger.info("Removed existing IEP2 container name=%s", name)
    except docker.errors.NotFound:
        pass

    client.containers.run(
        image=IEP2_IMAGE,
        name=name,
        command=["python", "-m", "services.iep2_vision.main"],
        environment={
            "CAMERA_ID":           camera_id,
            "CAMERA_CONFIG_ID":    camera_config_id or "",
            "STORE_ID":            store_id,
            "WINDOW_SECONDS":      str(window_seconds),
            "LOCAL_REDIS_URL":     LOCAL_REDIS_URL,
            "SERVER_REDIS_URL":    SERVER_REDIS_URL,
            "DATABASE_URL_SERVER": database_url_server,
            "LIVE_EMBED_FRAME":    LIVE_EMBED_FRAME,
            "LIVE_STREAM_ENABLED": "true",
        },
        volumes={
            IPC_SOCKETS_VOLUME: {"bind": "/tmp/sockets", "mode": "rw"},
            FRAME_STORE_VOLUME: {"bind": "/dev/shm/frames", "mode": "rw"},
        },
        network=DOCKER_NETWORK,
        detach=True,
        restart_policy={"Name": "on-failure", "MaximumRetryCount": 3},
    )
    logger.info("Started IEP2 container name=%s camera=%s", name, camera_id)
    return name


def stop_iep2(store_id: str, camera_id: str) -> None:
    import docker
    name = iep2_container_name(store_id, camera_id)
    try:
        c = _docker_client().containers.get(name)
        c.remove(force=True)
        logger.info("Stopped+removed IEP2 container name=%s", name)
    except docker.errors.NotFound:
        logger.info("IEP2 container not found name=%s", name)


# ── Fresh-restart helpers (DEBUG_MODE dev screen "Start" → start from frame 1) ──

def iep1_remove_all() -> None:
    """Remove every camera currently registered in IEP1 (resets windows/frame counters)."""
    from app.grpc_generated import iep1_control_pb2 as pb2
    ch = _iep1_channel()
    get = ch.unary_unary(
        "/retailvision.iep1.v1.Iep1Control/GetStatus",
        request_serializer=pb2.Empty.SerializeToString,
        response_deserializer=pb2.Iep1StatusResponse.FromString,
    )
    rm = ch.unary_unary(
        "/retailvision.iep1.v1.Iep1Control/RemoveCamera",
        request_serializer=pb2.RemoveCameraRequest.SerializeToString,
        response_deserializer=pb2.RemoveCameraResponse.FromString,
    )
    try:
        status = get(pb2.Empty(), timeout=10.0)
        for c in status.cameras:
            try:
                rm(pb2.RemoveCameraRequest(camera_id=c.camera_id), timeout=10.0)
                logger.info("IEP1 removed camera=%s", c.camera_id)
            except Exception as exc:
                logger.warning("IEP1 remove failed camera=%s: %s", c.camera_id, exc)
    except Exception as exc:
        logger.warning("IEP1 GetStatus failed during reset: %s", exc)


def stop_all_iep2_dev() -> None:
    """Remove all dev-spawned IEP2 containers (name prefix iep2_dev_)."""
    client = _docker_client()
    for c in client.containers.list(all=True):
        if c.name.startswith("iep2_dev_"):
            try:
                c.remove(force=True)
                logger.info("Removed IEP2 dev container name=%s", c.name)
            except Exception as exc:
                logger.warning("Failed removing %s: %s", c.name, exc)


def flush_pipeline_redis() -> None:
    """Delete IEP1/IEP2 streams, the batch_complete stream, live streams, and the
    per-camera local-id counters so tracking restarts from local_id 1."""
    import redis
    r = redis.Redis.from_url(SERVER_REDIS_URL)
    deleted = 0
    for pattern in ("stream:iep1:*", "stream:iep2:*", "iep2:id_counter:*"):
        keys = list(r.scan_iter(match=pattern, count=500))
        if keys:
            r.delete(*keys)
            deleted += len(keys)
    logger.info("Flushed %d pipeline Redis keys", deleted)
    try:
        r.close()
    except Exception:
        pass


def restart_iep3() -> None:
    """Restart the IEP3 reconciliation container for a clean coordinator state."""
    client = _docker_client()
    for c in client.containers.list(all=True):
        if "iep3_reconciliation" in c.name:
            try:
                c.restart(timeout=10)
                logger.info("Restarted IEP3 container name=%s", c.name)
            except Exception as exc:
                logger.warning("Failed restarting IEP3 %s: %s", c.name, exc)
            return
    logger.warning("IEP3 container not found for restart")
