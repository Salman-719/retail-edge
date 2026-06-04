import logging
import os
import time

import docker

logger = logging.getLogger(__name__)

IEP2_IMAGE          = os.environ.get("IEP2_IMAGE",           "retailvision-iep2:latest")
DOCKER_NETWORK      = os.environ.get("DOCKER_NETWORK",       "retail-edge_default")
IPC_SOCKETS_VOLUME  = os.environ.get("IPC_SOCKETS_VOLUME",   "retail-edge_ipc-sockets")
YOLO_HEALTH_TCP     = os.environ.get("YOLO_HEALTH_TCP_ADDR", "yolo-service:50052")
YOLO_HEALTH_TIMEOUT = int(os.environ.get("YOLO_HEALTH_TIMEOUT_S", "120"))

_client: docker.DockerClient | None = None


def get_client() -> docker.DockerClient:
    global _client
    if _client is None:
        _client = docker.from_env()
    return _client


def container_name(store_id: str, physical_camera_id: str) -> str:
    return f"iep2_{store_id}_{physical_camera_id}"


def _wait_for_yolo_serving(timeout_s: int = YOLO_HEALTH_TIMEOUT) -> None:
    """Block until yolo-service gRPC health reports SERVING, or raise TimeoutError.

    R7: IEP2 containers must not start until YOLO service is SERVING.
    Deviation from spec (Edge Agent checks): EEP checks via TCP health endpoint
    since yolo-service unix socket is not accessible from the EEP container.
    """
    import grpc
    from grpc_health.v1 import health_pb2, health_pb2_grpc

    deadline = time.monotonic() + timeout_s
    last_exc: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with grpc.insecure_channel(YOLO_HEALTH_TCP) as channel:
                stub = health_pb2_grpc.HealthStub(channel)
                resp = stub.Check(
                    health_pb2.HealthCheckRequest(service=""),
                    timeout=3.0,
                )
                if resp.status == health_pb2.HealthCheckResponse.SERVING:
                    logger.info("YOLO service is SERVING")
                    return
                logger.debug("YOLO service status=%s — waiting…", resp.status)
        except Exception as exc:
            last_exc = exc
            logger.debug("YOLO health check failed: %s — retrying…", exc)
        time.sleep(2)
    raise TimeoutError(
        f"YOLO service did not become SERVING within {timeout_s}s "
        f"(last error: {last_exc})"
    )


def start_iep2(
    store_id: str,
    physical_camera_id: str,
    camera_config_id: str,
    database_url_server: str,
    redis_url: str,
    s3_endpoint_url: str,
    s3_access_key: str,
    s3_secret_key: str,
    s3_bucket: str,
    window_seconds: float = 60.0,
) -> None:
    name = container_name(store_id, physical_camera_id)
    client = get_client()

    try:
        old = client.containers.get(name)
        old.remove(force=True)
        logger.info("Removed existing IEP2 container", extra={"container_name": name})
    except docker.errors.NotFound:
        pass

    _wait_for_yolo_serving()

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
            "DATABASE_URL_SERVER": database_url_server,
            "WINDOW_SECONDS":      str(window_seconds),
            "REDIS_URL":           redis_url,
            "S3_ENDPOINT_URL":     s3_endpoint_url,
            "S3_ACCESS_KEY":       s3_access_key,
            "S3_SECRET_KEY":       s3_secret_key,
            "S3_BUCKET":           s3_bucket,
        },
        volumes={
            IPC_SOCKETS_VOLUME: {"bind": "/tmp/sockets", "mode": "rw"},
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
