import logging

import grpc
import grpc.aio
from grpc_health.v1 import health, health_pb2, health_pb2_grpc
from grpc_reflection.v1alpha import reflection

from app.grpc_generated import agent_pb2, agent_pb2_grpc
from app.grpc_server.servicer import AgentServiceServicer

log = logging.getLogger(__name__)

_server: grpc.aio.Server | None = None

_REFLECTION_SERVICES = (
    "retailvision.agent.v1.AgentService",
    health_pb2.DESCRIPTOR.services_by_name["Health"].full_name,
    reflection.SERVICE_NAME,
)


async def start_grpc_server(port: int = 50051) -> grpc.aio.Server:
    global _server
    _server = grpc.aio.server()
    agent_pb2_grpc.add_AgentServiceServicer_to_server(AgentServiceServicer(), _server)
    health_servicer = health.HealthServicer()
    health_pb2_grpc.add_HealthServicer_to_server(health_servicer, _server)
    health_servicer.set("", health_pb2.HealthCheckResponse.SERVING)
    reflection.enable_server_reflection(_REFLECTION_SERVICES, _server)
    _server.add_insecure_port(f"[::]:{port}")
    await _server.start()
    log.info("gRPC server started  port=%d  reflection=enabled  health=SERVING", port)
    return _server


async def stop_grpc_server(grace: float = 5.0) -> None:
    if _server:
        await _server.stop(grace=grace)
        log.info("gRPC server stopped  grace=%.1fs", grace)
