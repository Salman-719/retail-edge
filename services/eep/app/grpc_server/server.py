import logging
import os

import grpc
import grpc.aio
from grpc_health.v1 import health, health_pb2, health_pb2_grpc
from grpc_reflection.v1alpha import reflection

from app.grpc_generated import agent_pb2, agent_pb2_grpc
from app.grpc_server.interceptor import AgentAuthInterceptor
from app.grpc_server.servicer import AgentServiceServicer

log = logging.getLogger(__name__)

_server: grpc.aio.Server | None = None

_REFLECTION_SERVICES = (
    "retailvision.agent.v1.AgentService",
    health_pb2.DESCRIPTOR.services_by_name["Health"].full_name,
    reflection.SERVICE_NAME,
)


def _load_server_credentials() -> grpc.ServerCredentials:
    cert_path = os.environ["GRPC_SERVER_CERT_PATH"]
    key_path  = os.environ["GRPC_SERVER_KEY_PATH"]
    with open(cert_path, "rb") as f:
        cert = f.read()
    with open(key_path, "rb") as f:
        key = f.read()
    return grpc.ssl_server_credentials([(key, cert)])


async def start_grpc_server(port: int | None = None) -> grpc.aio.Server:
    global _server
    if port is None:
        port = int(os.environ.get("GRPC_PORT", "50051"))
    _server = grpc.aio.server(interceptors=[AgentAuthInterceptor()])
    agent_pb2_grpc.add_AgentServiceServicer_to_server(AgentServiceServicer(), _server)
    health_servicer = health.HealthServicer()
    health_pb2_grpc.add_HealthServicer_to_server(health_servicer, _server)
    health_servicer.set("", health_pb2.HealthCheckResponse.SERVING)
    reflection.enable_server_reflection(_REFLECTION_SERVICES, _server)
    credentials = _load_server_credentials()
    _server.add_secure_port(f"[::]:{port}", credentials)
    await _server.start()
    log.info("gRPC server started  port=%d  tls=enabled  reflection=enabled  health=SERVING", port)
    return _server


async def stop_grpc_server(grace: float = 5.0) -> None:
    if _server:
        await _server.stop(grace=grace)
        log.info("gRPC server stopped  grace=%.1fs", grace)
