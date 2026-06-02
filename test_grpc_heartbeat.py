"""
gRPC test client — sends a Heartbeat to EEP and holds the connection open.

Usage (from retail-edge/):
    python test_grpc_heartbeat.py
    python test_grpc_heartbeat.py localhost:50051
    python test_grpc_heartbeat.py localhost:50051 <store_id>

Requires: pip install grpcio==1.64.0
"""
import asyncio
import os
import sys
import time

# Make EEP's generated stubs importable without installing the package.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "services", "eep"))

import grpc.aio
from app.grpc_generated import agent_pb2, agent_pb2_grpc

DEFAULT_TARGET   = "localhost:50051"
DEFAULT_STORE_ID = "d313d5a2-5a89-4429-8c05-2effd871302b"
HOLD_SECONDS     = 15  # stay connected so you can check DB / logs


async def main() -> None:
    target   = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_TARGET
    store_id = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_STORE_ID

    print(f"[*] Connecting to {target}")
    print(f"[*] store_id = {store_id}")

    async def _stream():
        yield agent_pb2.AgentMessage(
            heartbeat=agent_pb2.Heartbeat(
                store_id=store_id,
                agent_version="0.1.0",
                timestamp_ms=int(time.time() * 1000),
            )
        )
        print(f"[*] Heartbeat sent — holding connection for {HOLD_SECONDS}s")
        print("[*] Check EEP logs and the edge_agents table now.")
        await asyncio.sleep(HOLD_SECONDS)
        print("[*] Disconnecting.")

    async with grpc.aio.insecure_channel(target) as channel:
        stub = agent_pb2_grpc.AgentServiceStub(channel)
        async for msg in stub.Connect(_stream()):
            print("[<] EEP sent:", msg)


if __name__ == "__main__":
    asyncio.run(main())
