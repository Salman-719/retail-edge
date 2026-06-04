"""IEP1 daemon — single-process multi-camera gRPC service.

Exposes:
  Iep1Control service  on unix:///tmp/iep1-sockets/iep1_control.sock
  grpc.health.v1       on unix:///tmp/iep1-sockets/iep1_health.sock
"""
import asyncio
import logging
import os

import grpc
import grpc.aio
import redis.asyncio as aioredis
from grpc_health.v1 import health, health_pb2, health_pb2_grpc

from services.iep1_ingestion.app.grpc_generated import (
    iep1_control_pb2 as _pb2,
    iep1_control_pb2_grpc as _grpc,
)
from services.iep1_ingestion.app.worker import CameraWorker

logger = logging.getLogger(__name__)

IEP1_CONTROL_SOCK = os.environ.get(
    "IEP1_CONTROL_SOCK", "unix:///tmp/iep1-sockets/iep1_control.sock"
)
IEP1_HEALTH_SOCK  = os.environ.get(
    "IEP1_HEALTH_SOCK", "unix:///tmp/iep1-sockets/iep1_health.sock"
)
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")


class _Iep1ControlServicer(_grpc.Iep1ControlServicer):
    def __init__(self) -> None:
        self._workers: dict[str, CameraWorker] = {}
        self._redis: aioredis.Redis | None = None

    def set_redis(self, r: aioredis.Redis) -> None:
        self._redis = r

    async def AddCamera(self, request, context):
        camera_id = request.camera_id
        if camera_id in self._workers:
            return _pb2.AddCameraResponse(success=False, error="already_active")
        if not request.rtsp_url:
            return _pb2.AddCameraResponse(success=False, error="rtsp_url required")
        try:
            worker = CameraWorker(request)
            await worker.start(self._redis)
            self._workers[camera_id] = worker
            logger.info("AddCamera camera=%s", camera_id)
            return _pb2.AddCameraResponse(success=True)
        except Exception as exc:
            logger.exception("AddCamera failed camera=%s", camera_id)
            return _pb2.AddCameraResponse(success=False, error=str(exc))

    async def RemoveCamera(self, request, context):
        camera_id = request.camera_id
        worker = self._workers.pop(camera_id, None)
        if worker is None:
            return _pb2.RemoveCameraResponse(success=False)
        await worker.stop()
        logger.info("RemoveCamera camera=%s", camera_id)
        return _pb2.RemoveCameraResponse(success=True)

    async def GetStatus(self, request, context):
        cameras = [
            _pb2.CameraStatus(
                camera_id=w.camera_id,
                status=w.status,
                last_frame_ts=w.last_frame_ts,
                frames_dropped=w.frames_dropped,
            )
            for w in self._workers.values()
        ]
        return _pb2.Iep1StatusResponse(cameras=cameras)


async def run_daemon() -> None:
    redis_client = aioredis.Redis.from_url(REDIS_URL)

    servicer = _Iep1ControlServicer()
    servicer.set_redis(redis_client)

    health_servicer = health.HealthServicer()

    # ── Control server ────────────────────────────────────────────────────────
    control_server = grpc.aio.server()
    _grpc.add_Iep1ControlServicer_to_server(servicer, control_server)
    health_pb2_grpc.add_HealthServicer_to_server(health_servicer, control_server)
    health_servicer.set("", health_pb2.HealthCheckResponse.NOT_SERVING)
    control_server.add_insecure_port(IEP1_CONTROL_SOCK)

    # ── Health-only server ────────────────────────────────────────────────────
    health_server = grpc.aio.server()
    health_pb2_grpc.add_HealthServicer_to_server(health_servicer, health_server)
    health_server.add_insecure_port(IEP1_HEALTH_SOCK)

    await control_server.start()
    await health_server.start()
    logger.info("IEP1 daemon started  control=%s  health=%s", IEP1_CONTROL_SOCK, IEP1_HEALTH_SOCK)

    health_servicer.set("", health_pb2.HealthCheckResponse.SERVING)
    logger.info("IEP1 daemon SERVING — waiting for AddCamera calls")

    try:
        await control_server.wait_for_termination()
    finally:
        health_servicer.set("", health_pb2.HealthCheckResponse.NOT_SERVING)
        # stop all active workers gracefully
        for worker in list(servicer._workers.values()):
            await worker.stop()
        await redis_client.aclose()
        await health_server.stop(grace=2)
        logger.info("IEP1 daemon stopped")
