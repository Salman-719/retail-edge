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

_HERE   = os.path.dirname(os.path.abspath(__file__))
TMP_DIR = os.path.join(_HERE, "..", "tmp")
UI_DIR  = os.path.join(_HERE, "..", "ui")

STATE = {
    "frames":       [],
    "status":       "idle",
    "total_frames": 0,
    "events":       queue.Queue(),
}

# Set by /stop to break the pipeline loop early; reset at the start of each /upload.
_stop_event = threading.Event()

# Queries tracking_history by the camera_id column (stores physical_camera_id UUID as text).
_SNAPSHOT_SQL = """
    SELECT local_id, timestamp_ms, floor_x, floor_y, zone_id,
           bbox_confidence, bbox_area
    FROM tracking_history
    WHERE camera_id = $1
    ORDER BY timestamp_ms DESC
    LIMIT 50
"""
_COUNT_SQL = "SELECT COUNT(*) FROM tracking_history WHERE camera_id = $1"

# Resolves the active camera_config_id for a physical camera so IEP2 can load homography.
_ACTIVE_CONFIG_SQL = """
    SELECT cc.id AS camera_config_id
    FROM camera_configs cc
    JOIN store_config_versions scv ON scv.id = cc.version_id
    WHERE cc.physical_camera_id = $1
      AND scv.store_id          = $2
      AND scv.status            = 'active'
    LIMIT 1
"""


async def _query_snapshot(pool: asyncpg.Pool, cam_id: str) -> dict:
    rows  = await pool.fetch(_SNAPSHOT_SQL, cam_id)
    total = await pool.fetchval(_COUNT_SQL, cam_id)
    return {
        "type":       "db_snapshot",
        "total_rows": total or 0,
        "rows": [
            {
                "local_id":        str(r["local_id"]) if r["local_id"] is not None else None,
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
    physical_camera_id: str = Form(...),
    store_id: str = Form(...),
    use_physical_layer: str = Form('true'),
):
    os.makedirs(TMP_DIR, exist_ok=True)
    dest = os.path.join(TMP_DIR, f"{uuid.uuid4().hex}_{file.filename}")
    with open(dest, "wb") as f:
        f.write(await file.read())

    _stop_event.clear()           # reset from any previous run
    STATE["events"] = queue.Queue()
    STATE["frames"] = []
    STATE["status"] = "processing"

    db_url = os.getenv("DATABASE_URL", "")
    _with_physical = use_physical_layer.lower() == 'true'

    def pipeline_thread():
        async def _run():
            pool = None
            if db_url:
                try:
                    pool = await asyncpg.create_pool(db_url, min_size=1, max_size=2)
                except Exception:
                    log.exception("DB pool creation failed — snapshots disabled")

            # Optionally resolve the active camera_config_id for homography + zone projection.
            camera_config_id = None
            if _with_physical and pool:
                try:
                    row = await pool.fetchrow(
                        _ACTIVE_CONFIG_SQL,
                        uuid.UUID(physical_camera_id),
                        uuid.UUID(store_id),
                    )
                    if row:
                        camera_config_id = str(row["camera_config_id"])
                        log.info("Physical layer enabled  camera_config_id=%s", camera_config_id)
                    else:
                        log.warning("Physical layer requested but no active camera config found — "
                                    "falling back to ReID-only")
                except Exception:
                    log.exception("camera_config_id lookup failed — falling back to ReID-only")
            else:
                log.info("Physical layer disabled by request — running ReID-only")

            try:
                runtime = IEP2Runtime(Iep2Settings(
                    store_id=store_id,
                    camera_id=physical_camera_id,   # stored as camera_id in tracking_history
                    camera_config_id=camera_config_id,
                    database_url=db_url,
                ))
                frame_count = 0
                async with runtime.run(dest) as stream:
                    async for result in stream:
                        if _stop_event.is_set():
                            log.info("Pipeline stopped early by /stop request  camera=%s  frames=%d",
                                     physical_camera_id, frame_count)
                            break
                        record = asdict(result)
                        record["type"] = "frame"
                        STATE["frames"].append(record)
                        STATE["events"].put(record)
                        frame_count += 1
                        if pool and frame_count % 25 == 0:
                            STATE["events"].put(await _query_snapshot(pool, physical_camera_id))

                total = len(STATE["frames"])
                STATE["total_frames"] = total
                STATE["status"] = "done"

                if pool:
                    STATE["events"].put(await _query_snapshot(pool, physical_camera_id))

                STATE["events"].put({"type": "done", "status": "done", "total_frames": total})
                log.info("Pipeline done  camera=%s  frames=%d", physical_camera_id, total)
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


@app.post("/stop")
async def stop():
    """Signal the running pipeline to stop after the current frame."""
    _stop_event.set()
    return {"status": "stopping"}


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
