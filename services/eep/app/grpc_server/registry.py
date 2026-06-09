import asyncio
import logging
from typing import Literal

from app.grpc_generated import agent_pb2
from app.metrics import EEP_GRPC_CONNECTIONS

log = logging.getLogger(__name__)

_connections: dict[str, asyncio.Queue] = {}


async def register(store_id: str) -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue(maxsize=100)
    _connections[store_id] = q
    EEP_GRPC_CONNECTIONS.set(len(_connections))
    return q


def deregister(store_id: str) -> None:
    _connections.pop(store_id, None)
    EEP_GRPC_CONNECTIONS.set(len(_connections))


async def send_command(
    store_id: str, msg: agent_pb2.ControlMessage
) -> Literal["sent", "disconnected", "queue_full"]:
    q = _connections.get(store_id)
    if q is None:
        return "disconnected"
    try:
        q.put_nowait(msg)
        return "sent"
    except asyncio.QueueFull:
        log.warning("Command queue full for store=%s", store_id)
        return "queue_full"


def connected_stores() -> list[str]:
    return list(_connections.keys())
