"""
Run from inside the EEP container to test the gRPC heartbeat loop.
    docker compose exec eep python test_heartbeat.py

Connects to localhost:50051 (the server running in the same container).
Holds the connection open for 10s so you can check DB / logs.
"""
import asyncio
import sys
import time

import grpc
import grpc.aio

from app.grpc_generated import agent_pb2, agent_pb2_grpc

STORE_ID     = "d313d5a2-5a89-4429-8c05-2effd871302b"
TARGET       = "localhost:50051"
HOLD_SECONDS = 10


async def main() -> None:
    print(f"[*] Connecting to {TARGET}", flush=True)

    async def _stream():
        msg = agent_pb2.AgentMessage(
            heartbeat=agent_pb2.Heartbeat(
                store_id=STORE_ID,
                agent_version="0.1.0",
                timestamp_ms=int(time.time() * 1000),
            )
        )
        print("[*] Sending heartbeat ...", flush=True)
        yield msg
        print(f"[*] Heartbeat sent — sleeping {HOLD_SECONDS}s", flush=True)
        await asyncio.sleep(HOLD_SECONDS)
        print("[*] Done — disconnecting.", flush=True)

    try:
        async with grpc.aio.insecure_channel(TARGET) as channel:
            stub = agent_pb2_grpc.AgentServiceStub(channel)
            async for ctrl in stub.Connect(_stream()):
                print("[<] EEP sent control message:", ctrl, flush=True)
    except grpc.aio.AioRpcError as exc:
        print(f"[!] gRPC error: {exc.code()} — {exc.details()}", file=sys.stderr, flush=True)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
