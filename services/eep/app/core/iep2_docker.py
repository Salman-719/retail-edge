import logging
import os

import docker

logger = logging.getLogger(__name__)

IEP2_IMAGE     = os.environ.get("IEP2_IMAGE",     "retailvision-iep2:latest")
DOCKER_NETWORK = os.environ.get("DOCKER_NETWORK", "retail-edge_default")

_client: docker.DockerClient | None = None


def get_client() -> docker.DockerClient:
    global _client
    if _client is None:
        _client = docker.from_env()
    return _client


def container_name(store_id: str, physical_camera_id: str) -> str:
    return f"iep2_{store_id}_{physical_camera_id}"


def start_iep2(
    store_id: str,
    physical_camera_id: str,
    camera_config_id: str,
    database_url: str,
    redis_url: str,
    s3_endpoint_url: str,
    s3_access_key: str,
    s3_secret_key: str,
    s3_bucket: str,
) -> None:
    name = container_name(store_id, physical_camera_id)
    client = get_client()

    try:
        old = client.containers.get(name)
        old.remove(force=True)
        logger.info("Removed existing IEP2 container", extra={"container_name": name})
    except docker.errors.NotFound:
        pass

    client.containers.run(
        image=IEP2_IMAGE,
        name=name,
        command=[
            "python", "-m", "services.iep2_vision.main",
            "--store-id",         store_id,
            "--camera-id",        physical_camera_id,
            "--source",           "redis",
            "--camera-config-id", camera_config_id,
        ],
        environment={
            "DATABASE_URL":    database_url,
            "REDIS_URL":       redis_url,
            "S3_ENDPOINT_URL": s3_endpoint_url,
            "S3_ACCESS_KEY":   s3_access_key,
            "S3_SECRET_KEY":   s3_secret_key,
            "S3_BUCKET":       s3_bucket,
        },
        network=DOCKER_NETWORK,
        detach=True,
        restart_policy={"Name": "on-failure", "MaximumRetryCount": 3},
    )
    logger.info("Started IEP2 container", extra={"container_name": name})


def stop_iep2(store_id: str, physical_camera_id: str) -> None:
    name = container_name(store_id, physical_camera_id)
    try:
        container = get_client().containers.get(name)
        container.stop(timeout=10)
        logger.info("Stopped IEP2 container", extra={"container_name": name})
    except docker.errors.NotFound:
        logger.info("IEP2 container not found", extra={"container_name": name})


def get_iep2_status(store_id: str, physical_camera_id: str) -> str:
    name = container_name(store_id, physical_camera_id)
    try:
        container = get_client().containers.get(name)
        return "running" if container.status == "running" else "stopped"
    except docker.errors.NotFound:
        return "stopped"
