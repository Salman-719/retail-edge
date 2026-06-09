"""Docker-based IEP2 lifecycle management for the Edge Agent.

Fallback backend used when k3s is not available (laptop / dev machines).
Exposes the same public interface as k8s_manager.py so agent.py can switch
backends transparently at startup.

Container naming convention: iep2-prod-{camera_id}
  (distinct from dev_orchestrator's iep2_dev_{camera_id})
"""
import logging
import os

log = logging.getLogger(__name__)

IEP2_IMAGE         = os.environ.get("IEP2_IMAGE",         "retail-edge-iep2_vision:latest")
DOCKER_NETWORK     = os.environ.get("DOCKER_NETWORK",     "retail-edge_default")
IPC_SOCKETS_VOLUME = os.environ.get("IPC_SOCKETS_VOLUME", "retail-edge_ipc-sockets")
FRAME_STORE_VOLUME = os.environ.get("FRAME_STORE_VOLUME", "retail-edge_frame-store")
REDIS_CA_CERT_PATH = os.environ.get(
    "REDIS_CA_CERT_PATH", "/etc/retailvision/certs/ca.crt"
)

_client = None

# In-memory env cache: camera_id → env dict.
# Rebuilt from running container env vars on Edge Agent restart.
_config_cache: dict[str, dict] = {}


def init_k8s_clients() -> None:
    """Named to match k8s_manager interface. Initialises the Docker client."""
    global _client
    try:
        import docker  # type: ignore[import-untyped]
        _client = docker.from_env()
        log.info("docker_manager: Docker client initialised (using Docker backend for IEP2)")
    except Exception as exc:
        log.warning("docker_manager: Docker unavailable — IEP2 cannot be managed (%s)", exc)


def is_available() -> bool:
    return _client is not None


def _container_name(camera_id: str) -> str:
    return f"iep2-prod-{camera_id}"


# ── ConfigMap equivalent ───────────────────────────────────────────────────────

def apply_camera_configmap(camera_id: str, env_data: dict) -> None:
    """Cache env data for use by apply_iep2_deployment."""
    _config_cache[camera_id] = env_data


# ── IEP2 container lifecycle ───────────────────────────────────────────────────

def apply_iep2_deployment(camera_id: str) -> None:
    """Start (or replace) the IEP2 Docker container for a camera."""
    if _client is None:
        raise RuntimeError("docker_manager: Docker client not initialised")

    import docker.errors  # type: ignore[import-untyped]

    env  = _config_cache.get(camera_id, {})
    name = _container_name(camera_id)

    try:
        _client.containers.get(name).remove(force=True)
        log.info("docker_manager: removed existing container %s", name)
    except docker.errors.NotFound:
        pass

    volumes = {
        IPC_SOCKETS_VOLUME: {"bind": "/tmp/sockets",    "mode": "rw"},
        FRAME_STORE_VOLUME: {"bind": "/dev/shm/frames", "mode": "rw"},
    }
    if os.path.isfile(REDIS_CA_CERT_PATH):
        volumes[REDIS_CA_CERT_PATH] = {
            "bind": "/etc/retailvision/certs/ca.crt",
            "mode": "ro",
        }

    _client.containers.run(
        image=IEP2_IMAGE,
        name=name,
        environment=env,
        volumes=volumes,
        network=DOCKER_NETWORK,
        detach=True,
        restart_policy={"Name": "on-failure", "MaximumRetryCount": 3},
        labels={
            "component":  "iep2",
            "camera-id":  camera_id,
            "managed-by": "edge-agent",
        },
    )
    log.info("docker_manager: started container %s  image=%s", name, IEP2_IMAGE)


def delete_iep2(camera_id: str) -> None:
    """Remove the IEP2 container for a camera. Idempotent."""
    _config_cache.pop(camera_id, None)
    if _client is None:
        return

    import docker.errors  # type: ignore[import-untyped]

    try:
        _client.containers.get(_container_name(camera_id)).remove(force=True)
        log.info("docker_manager: removed container %s", _container_name(camera_id))
    except docker.errors.NotFound:
        pass


# ── State queries ──────────────────────────────────────────────────────────────

def list_active_iep2_deployments() -> list[dict]:
    """Return one dict per active IEP2 container with its env data.

    Rebuilds _config_cache from container env so the Edge Agent can restore
    cameras after its own restart without needing EEP to resync.
    """
    if _client is None:
        return []
    try:
        containers = _client.containers.list(
            filters={"label": ["component=iep2", "managed-by=edge-agent"]}
        )
    except Exception as exc:
        log.warning("docker_manager: failed to list IEP2 containers: %s", exc)
        return []

    result = []
    for c in containers:
        camera_id = c.labels.get("camera-id", "")
        if not camera_id:
            continue
        env_dict: dict[str, str] = {}
        for entry in (c.attrs.get("Config", {}).get("Env") or []):
            if "=" in entry:
                k, _, v = entry.partition("=")
                env_dict[k] = v
        _config_cache[camera_id] = env_dict
        result.append({"camera_id": camera_id, **env_dict})

    return result


def get_active_camera_ids() -> list[str]:
    if _client is None:
        return []
    try:
        containers = _client.containers.list(
            filters={
                "label":  ["component=iep2", "managed-by=edge-agent"],
                "status": "running",
            }
        )
        return [c.labels["camera-id"] for c in containers if c.labels.get("camera-id")]
    except Exception as exc:
        log.warning("docker_manager: failed to list active cameras: %s", exc)
        return []


def get_camera_k8s_status(camera_id: str) -> str:
    """Return a normalised status string (mirrors k8s_manager interface)."""
    if _client is None:
        return "unknown"

    import docker.errors  # type: ignore[import-untyped]

    try:
        status = _client.containers.get(_container_name(camera_id)).status
        return {
            "running":    "running",
            "created":    "starting",
            "restarting": "starting",
            "exited":     "failed",
            "dead":       "failed",
            "paused":     "failed",
        }.get(status, "unknown")
    except docker.errors.NotFound:
        return "not_found"
    except Exception as exc:
        log.warning("docker_manager: status query failed  camera=%s: %s", camera_id, exc)
        return "unknown"
