import asyncio

from app.grpc_generated import agent_pb2

_connections: dict[str, asyncio.Queue] = {}


async def register(store_id: str) -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue()
    _connections[store_id] = q
    return q


def deregister(store_id: str) -> None:
    _connections.pop(store_id, None)


async def send_command(store_id: str, msg: agent_pb2.ControlMessage) -> bool:
    q = _connections.get(store_id)
    if q is None:
        return False
    await q.put(msg)
    return True


def connected_stores() -> list[str]:
    return list(_connections.keys())
