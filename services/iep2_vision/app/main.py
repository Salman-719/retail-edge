"""FastAPI app: HTTP upload + WebSocket stream.

Thin transport adapter only. All pipeline logic lives in runtime.py.
This module owns: request parsing, tmp file handling, thread/queue bridge,
WebSocket drain, and static UI serving. Nothing else.
"""
import asyncio
import logging
import os
import queue
import threading
import uuid
from contextlib import asynccontextmanager
from dataclasses import asdict

import asyncpg
from fastapi import FastAPI, UploadFile, File, Form, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse

from ..runtime import IEP2Runtime, Iep2Settings

log = logging.getLogger("iep2")

_HERE  = os.path.dirname(os.path.abspath(__file__))
TMP_DIR = os.path.join(_HERE, "..", "tmp")
UI_DIR  = os.path.join(_HERE, "..", "ui")

# All pipeline state lives here — no DB, no model references.
STATE = {
    "frames":       [],
    "status":       "idle",
    "total_frames": 0,
    "events":       queue.Queue(),
}

_SNAPSHOT_SQL = """
    SELECT local_id, timestamp_ms, floor_x, floor_y, zone_id,
           bbox_confidence, bbox_area
    FROM tracking_history
    WHERE camera_id = $1
    ORDER BY timestamp_ms DESC
    LIMIT 50
"""

_COUNT_SQL = "SELECT COUNT(*) FROM tracking_history WHERE camera_id = $1"


async def _query_snapshot(pool: asyncpg.Pool, camera_id: str) -> dict:
    rows = await pool.fetch(_SNAPSHOT_SQL, camera_id)
    total = await pool.fetchval(_COUNT_SQL, camera_id)
    return {
        "type": "db_snapshot",
        "total_rows": total or 0,
        "rows": [
            {
                "local_id":        str(r["local_id"])  if r["local_id"]  is not None else None,
                "timestamp_ms":    r["timestamp_ms"],
                "floor_x":         r["floor_x"],
                "floor_y":         r["floor_y"],
                "zone_id":         str(r["zone_id"]) if r["zone_id"] is not None else None,
                "bbox_confidence": r["bbox_confidence"],
                "bbox_area":       r["bbox_area"],
            }
            for r in rows
        ],
    }


@asynccontextmanager
async def lifespan(app: FastAPI):
    _setup_logging()
    os.makedirs(TMP_DIR, exist_ok=True)
    yield


def _setup_logging():
    level = os.getenv("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=level,
        format="%(asctime)s  %(levelname)-8s  %(name)-30s  %(message)s",
        datefmt="%H:%M:%S",
        force=True,
    )


app = FastAPI(lifespan=lifespan)


@app.post("/upload")
async def upload(
    file: UploadFile = File(...),
    camera_id: str = Form(...),
):
    os.makedirs(TMP_DIR, exist_ok=True)
    dest = os.path.join(TMP_DIR, f"{uuid.uuid4().hex}_{file.filename}")
    with open(dest, "wb") as f:
        f.write(await file.read())

    # Fresh event queue for this upload.
    STATE["events"] = queue.Queue()
    STATE["frames"] = []
    STATE["status"] = "processing"

    db_url = os.getenv("DATABASE_URL", "")

    def pipeline_thread():
        async def _run():
            pool = None
            if db_url:
                try:
                    pool = await asyncpg.create_pool(db_url, min_size=1, max_size=2)
                except Exception:
                    log.exception("DB pool creation failed — snapshots disabled")

            try:
                runtime = IEP2Runtime(Iep2Settings(
                    store_id="default",
                    camera_id=camera_id,
                    database_url=db_url,
                ))
                frame_count = 0
                async with runtime.run(dest) as stream:
                    async for result in stream:
                        record = asdict(result)
                        record["type"] = "frame"
                        STATE["frames"].append(record)
                        STATE["events"].put(record)
                        frame_count += 1
                        if pool and frame_count % 25 == 0:
                            STATE["events"].put(await _query_snapshot(pool, camera_id))

                total = len(STATE["frames"])
                STATE["total_frames"] = total
                STATE["status"] = "done"

                if pool:
                    STATE["events"].put(await _query_snapshot(pool, camera_id))

                STATE["events"].put({"type": "done", "status": "done", "total_frames": total})
                log.info("Pipeline done  camera=%s  frames=%d", camera_id, total)
            finally:
                if pool:
                    await pool.close()

        asyncio.run(_run())

    threading.Thread(target=pipeline_thread, daemon=True).start()

    return {"status": "processing", "filename": file.filename}


@app.websocket("/ws")
async def ws(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            try:
                msg = STATE["events"].get_nowait()
            except queue.Empty:
                await asyncio.sleep(0.05)
                continue

            await websocket.send_json(msg)
            if isinstance(msg, dict) and msg.get("type") == "done":
                break
    except WebSocketDisconnect:
        pass


@app.get("/frames")
async def frames():
    return {
        "status":       STATE["status"],
        "total_frames": STATE["total_frames"],
        "frames":       STATE["frames"],
    }


@app.post("/clear-tmp")
async def clear_tmp():
    """Delete all uploaded video files from the tmp directory."""
    removed = 0
    if os.path.isdir(TMP_DIR):
        for name in os.listdir(TMP_DIR):
            path = os.path.join(TMP_DIR, name)
            if os.path.isfile(path):
                os.remove(path)
                removed += 1
    return {"removed": removed}


@app.get("/")
async def index():
    return FileResponse(os.path.join(UI_DIR, "index.html"))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8002)
