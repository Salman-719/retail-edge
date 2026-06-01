import grpc
import grpc.aio

from app.grpc_generated import agent_pb2_grpc
from app.grpc_server.servicer import AgentServiceServicer

_server: grpc.aio.Server | None = None


async def start_grpc_server(port: int = 50051) -> grpc.aio.Server:
    global _server
    _server = grpc.aio.server()
    agent_pb2_grpc.add_AgentServiceServicer_to_server(AgentServiceServicer(), _server)
    _server.add_insecure_port(f"[::]:{port}")
    await _server.start()
    return _server


async def stop_grpc_server(grace: float = 5.0) -> None:
    if _server:
        await _server.stop(grace=grace)
