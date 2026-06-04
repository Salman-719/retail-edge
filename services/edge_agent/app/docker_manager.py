"""Docker lifecycle management for the edge pipeline.

Manages:
  - yolo-service / osnet-service  (long-lived, one per device, GPU)
  - iep1-daemon                   (long-lived, one per device)
  - iep2_{store_id}_{camera_id}   (per-camera, started/stopped per schedule)

All functions are synchronous blocking — call from a ThreadPoolExecutor only.
"""
import logging
import os

import docker
import docker.errors

logger = logging.getLogger(__name__)

# ── Environment ────────────────────────────────────────────────────────────────
DOCKER_NETWORK      = os.environ.get("DOCKER_NETWORK",      "retail-edge_default")
IPC_SOCKETS_VOLUME  = os.environ.get("IPC_SOCKETS_VOLUME",  "retail-edge_ipc-sockets")
FRAME_STORE_VOLUME  = os.environ.get("FRAME_STORE_VOLUME",  "retail-edge_frame-store")
IEP1_SOCKETS_VOLUME = os.environ.get("IEP1_SOCKETS_VOLUME", "retail-edge_iep1-sockets")

IEP1_IMAGE  = os.environ.get("IEP1_IMAGE",  "retailvision-iep1:latest")
IEP2_IMAGE  = os.environ.get("IEP2_IMAGE",  "retailvision-iep2:latest")
YOLO_IMAGE  = os.environ.get("YOLO_IMAGE",  "retailvision-yolo-service:latest")
OSNET_IMAGE = os.environ.get("OSNET_IMAGE", "retailvision-osnet-service:latest")

_client: docker.DockerClient | None = None


def get_client() -> docker.DockerClient:
    global _client
    if _client is None:
        _client = docker.from_env()
    return _client


# ── Container naming ───────────────────────────────────────────────────────────

def iep2_container_name(store_id: str, camera_id: str) -> str:
    return f"iep2_{store_id}_{camera_id}"


# ── Long-running service management (R10) ─────────────────────────────────────

def ensure_service_running(
    name: str,
    image: str,
    volumes: dict,
    env: dict | None = None,
    runtime: str | None = None,
) -> None:
    """Start a long-running service container if not already running.

    If the container exists but is stopped or crashed, remove it and recreate.
    If it is running, do nothing.
    """
    client = get_client()
    try:
        c = client.containers.get(name)
        if c.status == "running":
            logger.debug("Service already running: %s", name)
            return
        logger.warning("Service %s in state '%s' — removing and restarting", name, c.status)
        c.remove(force=True)
    except docker.errors.NotFound:
        pass

    run_kwargs: dict = dict(
        image=image,
        name=name,
        detach=True,
        network=DOCKER_NETWORK,
        restart_policy={"Name": "on-failure", "MaximumRetryCount": 5},
        volumes=volumes,
    )
    if env:
        run_kwargs["environment"] = env
    if runtime:
        run_kwargs["runtime"] = runtime

    client.containers.run(**run_kwargs)
    logger.info("Started service container: %s  image=%s", name, image)


# ── Per-camera IEP2 management ─────────────────────────────────────────────────

def start_iep2(store_id: str, camera_id: str, env: dict) -> None:
    """Start an IEP2 container for the given camera.

    Removes any stale container (stopped or crashed) before starting fresh.
    """
    name = iep2_container_name(store_id, camera_id)
    client = get_client()
    try:
        old = client.containers.get(name)
        old.remove(force=True)
        logger.info("Removed stale IEP2 container: %s", name)
    except docker.errors.NotFound:
        pass

    client.containers.run(
        image=IEP2_IMAGE,
        name=name,
        detach=True,
        network=DOCKER_NETWORK,
        restart_policy={"Name": "on-failure", "MaximumRetryCount": 3},
        volumes={
            IPC_SOCKETS_VOLUME: {"bind": "/tmp/sockets",    "mode": "rw"},
            FRAME_STORE_VOLUME: {"bind": "/dev/shm/frames", "mode": "rw"},
        },
        environment=env,
    )
    logger.info("Started IEP2 container: %s", name)


def stop_iep2(store_id: str, camera_id: str) -> None:
    """Stop and remove an IEP2 container. Idempotent — safe if already gone."""
    name = iep2_container_name(store_id, camera_id)
    client = get_client()
    try:
        c = client.containers.get(name)
        c.stop(timeout=30)
        c.remove()
        logger.info("Stopped and removed IEP2 container: %s", name)
    except docker.errors.NotFound:
        logger.debug("IEP2 container not found (already gone): %s", name)


# ── Status query (R7) ──────────────────────────────────────────────────────────

def get_container_status(name: str) -> str:
    """Return the raw Docker status string for a container.

    Possible values: "running", "restarting", "exited", "dead", "created",
    "paused", "removing", "not_found".
    """
    try:
        c = get_client().containers.get(name)
        return c.status
    except docker.errors.NotFound:
        return "not_found"


# ── Startup rebuild helper (R2) ────────────────────────────────────────────────

def list_running_iep2_containers() -> list[tuple[str, str]]:
    """Return [(store_id, camera_id)] for all running iep2_* containers."""
    result = []
    for c in get_client().containers.list():
        name = c.name
        if not name.startswith("iep2_"):
            continue
        parts = name.split("_", 2)
        if len(parts) == 3:
            _, store_id, camera_id = parts
            result.append((store_id, camera_id))
    return result
