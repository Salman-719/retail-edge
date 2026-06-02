import logging

import docker

logger = logging.getLogger(__name__)

_client: docker.DockerClient | None = None


def get_client() -> docker.DockerClient:
    global _client
    if _client is None:
        _client = docker.from_env()
    return _client


def container_name(store_id: str, camera_id: str) -> str:
    return f"iep1_{store_id}_{camera_id}"


def start_iep1(cmd, image: str, network: str) -> None:
    name = container_name(cmd.store_id, cmd.camera_id)
    client = get_client()

    # Remove existing container (stopped or crashed) before starting fresh.
    try:
        old = client.containers.get(name)
        old.remove(force=True)
        logger.info("Removed existing container", extra={"container_name": name})
    except docker.errors.NotFound:
        pass

    client.containers.run(
        image=image,
        name=name,
        command=[
            "python", "-m", "services.iep1_ingestion.app.main",
            "--store-id", cmd.store_id,
            "--camera-id", cmd.camera_id,
            "--rtsp", cmd.rtsp_url,
            "--fps", str(cmd.target_fps),
            "--window", str(cmd.window_seconds),
        ],
        environment={
            "S3_ENDPOINT_URL": cmd.s3_config.endpoint_url,
            "S3_ACCESS_KEY":   cmd.s3_config.access_key,
            "S3_SECRET_KEY":   cmd.s3_config.secret_key,
            "S3_BUCKET":       cmd.s3_config.bucket,
            "REDIS_URL":       cmd.redis_url,
        },
        network=network,
        detach=True,
        restart_policy={"Name": "on-failure", "MaximumRetryCount": 3},
    )
    logger.info("Started IEP1 container", extra={"container_name": name})


def stop_iep1(store_id: str, camera_id: str) -> None:
    name = container_name(store_id, camera_id)
    client = get_client()
    try:
        container = client.containers.get(name)
        container.stop(timeout=10)
        logger.info("Stopped IEP1 container", extra={"container_name": name})
    except docker.errors.NotFound:
        logger.info("Container not found, already gone", extra={"container_name": name})


def get_status(store_id: str, camera_id: str) -> str:
    name = container_name(store_id, camera_id)
    try:
        container = get_client().containers.get(name)
        return "running" if container.status == "running" else "stopped"
    except docker.errors.NotFound:
        return "stopped"
