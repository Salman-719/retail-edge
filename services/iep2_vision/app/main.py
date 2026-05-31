"""FastAPI app: HTTP upload + WebSocket stream.

This module is the orchestrator only. It owns no detection logic, no
frame-extraction logic, and no tracking logic — it imports those from their
owning modules via relative paths (no package install, no __init__.py).
"""
import asyncio
import base64
import io
import os
import queue
import threading
import uuid

import cv2
import numpy as np
from fastapi import FastAPI, UploadFile, File, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from PIL import Image

from ..video_ingestor.ingestor import extract_frames
from ..detector.detector import detect
from ..tracker.tracker import create_tracker, update

# Wire-transfer cap: never encode frames wider than this (hard constraint).
MAX_WIRE_WIDTH = 640

_HERE = os.path.dirname(os.path.abspath(__file__))
TMP_DIR = os.path.join(_HERE, "..", "tmp")
UI_DIR = os.path.join(_HERE, "..", "ui")

app = FastAPI()

# All pipeline state lives in this module-level dict — no DB this phase.
STATE = {
    "frames": [],          # list of {frame_index, frame_b64, tracks, new_entries}
    "status": "idle",      # idle | processing | done
    "total_frames": 0,
    "events": queue.Queue(),  # per-frame messages for the WebSocket to drain
}


@app.on_event("startup")
def _ensure_tmp():
    os.makedirs(TMP_DIR, exist_ok=True)


def _encode_frame(frame: np.ndarray) -> tuple[str, float]:
    """Resize to max 640px wide then base64-encode as JPEG for the wire.

    Returns (base64_jpeg, scale) where scale is the factor applied to the
    frame so callers can map detection bboxes into the encoded image's
    coordinate space.
    """
    h, w = frame.shape[:2]
    scale = 1.0
    if w > MAX_WIRE_WIDTH:
        scale = MAX_WIRE_WIDTH / w
        frame = cv2.resize(frame, (MAX_WIRE_WIDTH, int(h * scale)))

    # BGR (OpenCV) -> RGB (Pillow)
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    buf = io.BytesIO()
    Image.fromarray(rgb).save(buf, format="JPEG")
    return base64.b64encode(buf.getvalue()).decode("ascii"), scale


def _run_pipeline(video_path: str):
    """Plain worker thread: extract -> detect -> track, frame by frame, in memory."""
    STATE["frames"] = []
    STATE["status"] = "processing"
    STATE["total_frames"] = 0

    # Tracker lifetime is scoped to this upload thread (hard constraint).
    tracker = create_tracker()
    # seen_ids lives here in main.py (spec rule 3 — not in tracker.py).
    seen_ids: set[int] = set()

    frame_index = 0
    for frame in extract_frames(video_path):
        detections = detect(frame)
        frame_b64, scale = _encode_frame(frame)
        # Scale bboxes into the encoded image's coordinate space before tracking.
        if scale != 1.0:
            for d in detections:
                d["bbox"] = [c * scale for c in d["bbox"]]

        tracks = update(tracker, detections)

        new_entries = [t["track_id"] for t in tracks if t["track_id"] not in seen_ids]
        seen_ids.update(new_entries)

        record = {
            "frame_index": frame_index,
            "frame_b64": frame_b64,
            "tracks": tracks,
            "new_entries": new_entries,
        }
        STATE["frames"].append(record)
        STATE["events"].put(record)
        frame_index += 1

    STATE["total_frames"] = frame_index
    STATE["status"] = "done"
    STATE["events"].put({"status": "done", "total_frames": frame_index})


@app.post("/upload")
async def upload(file: UploadFile = File(...)):
    os.makedirs(TMP_DIR, exist_ok=True)
    dest = os.path.join(TMP_DIR, f"{uuid.uuid4().hex}_{file.filename}")
    with open(dest, "wb") as f:
        f.write(await file.read())

    # Reset the event queue for a fresh run.
    STATE["events"] = queue.Queue()

    # Explicit thread — no BackgroundTasks, no executor (hard constraint).
    thread = threading.Thread(target=_run_pipeline, args=(dest,), daemon=True)
    thread.start()

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
        "status": STATE["status"],
        "total_frames": STATE["total_frames"],
        "frames": STATE["frames"],
    }


@app.get("/")
async def index():
    return FileResponse(os.path.join(UI_DIR, "index.html"))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8002)
