"""Live Bridge — bridges Redis stream:iep2:live:{camera_id} to WebSocket clients.

One background task per camera, one asyncio.Queue per connected client.
Task starts on first connect, stops on last disconnect. No shared state with
EEP, IEP1, or IEP2.
"""
import asyncio
import json
import logging
import os
from typing import Dict, Set

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from .redis_reader import read_camera_stream
from .s3_presign import generate_presigned_url

log = logging.getLogger("live_bridge")

SERVER_REDIS_URL = os.environ.get("SERVER_REDIS_URL", "redis://redis:6379/0")
PRESIGNED_URL_EXPIRY = int(os.environ.get("PRESIGNED_URL_EXPIRY", "30"))

# camera_id -> set[asyncio.Queue]  (one Queue per connected client)
_registry: Dict[str, Set[asyncio.Queue]] = {}
# camera_id -> asyncio.Task
_tasks: Dict[str, asyncio.Task] = {}

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def _startup():
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        datefmt="%H:%M:%S",
    )


@app.get("/health")
async def health():
    return {"status": "ok"}


async def _on_frame(camera_id: str, payload: dict) -> None:
    """Presign frame URL and broadcast to all queued clients for this camera."""
    s3_key = payload.get("s3_key", "")
    if not s3_key:
        return

    frame_url = await generate_presigned_url(s3_key, PRESIGNED_URL_EXPIRY)
    if frame_url is None:
        return

    msg = json.dumps({
        "camera_id": payload.get("camera_id"),
        "timestamp_ms": payload.get("timestamp_ms"),
        "frame_url": frame_url,
        "detections": payload.get("detections", []),
    })

    for queue in list(_registry.get(camera_id, set())):
        try:
            queue.put_nowait(msg)
        except asyncio.QueueFull:
            pass  # slow client — drop frame, never block


async def _reader_task(camera_id: str) -> None:
    async def on_message(payload: dict):
        await _on_frame(camera_id, payload)

    await read_camera_stream(camera_id, SERVER_REDIS_URL, on_message)


@app.websocket("/ws/live/{camera_id}")
async def ws_live(websocket: WebSocket, camera_id: str):
    await websocket.accept()

    queue: asyncio.Queue = asyncio.Queue(maxsize=32)

    if camera_id not in _registry:
        _registry[camera_id] = set()
    _registry[camera_id].add(queue)

    if camera_id not in _tasks or _tasks[camera_id].done():
        _tasks[camera_id] = asyncio.create_task(_reader_task(camera_id))
        log.info("Started reader task  camera=%s", camera_id)

    try:
        while True:
            msg = await queue.get()
            await websocket.send_text(msg)
    except (WebSocketDisconnect, Exception):
        pass
    finally:
        _registry[camera_id].discard(queue)
        if not _registry.get(camera_id):
            _registry.pop(camera_id, None)
            task = _tasks.pop(camera_id, None)
            if task and not task.done():
                task.cancel()
                log.info("Cancelled reader task  camera=%s (no clients)", camera_id)
