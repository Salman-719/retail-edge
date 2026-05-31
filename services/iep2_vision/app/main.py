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

from fastapi import FastAPI, UploadFile, File, Form, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse

from ..runtime import IEP2Runtime

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


@asynccontextmanager
async def lifespan(app: FastAPI):
    _setup_logging()
    os.makedirs(TMP_DIR, exist_ok=True)
    log.info("Loading models…")
    app.state.runtime = IEP2Runtime()
    log.info("Models loaded — ready.")
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

    runtime = app.state.runtime

    def pipeline_thread():
        log.info("Pipeline started  camera=%s  file=%s", camera_id, file.filename)
        with runtime.run(dest, camera_id) as stream:
            for result in stream:
                record = asdict(result)
                STATE["frames"].append(record)
                STATE["events"].put(record)
        total = len(STATE["frames"])
        STATE["total_frames"] = total
        STATE["status"] = "done"
        STATE["events"].put({"status": "done", "total_frames": total})
        log.info("Pipeline done  camera=%s  frames=%d", camera_id, total)

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
            if isinstance(msg, dict) and msg.get("status") == "done":
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
