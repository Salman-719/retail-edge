"""QA-only upload/review server.

This intentionally runs the Marji IEP2 -> IEP3 chain in one HTTP-triggered
process for local validation. Production deployment uses IAIP1 frame-ref events,
IAIP2 detector workers, and IEP3 reconciliation workers instead.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path
from threading import RLock
from typing import Any

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import bindparam, text

from common.config import get_settings
from common.db.engine import session_scope
from common.db.migrate import apply_schema
from common.utils.jsonio import read_json, write_json_atomic
from tools.demo.render import render_camera
from tools.demo.review_page import render_review_page
from tools.orchestrator import RunPlan, load_calibrations, run
from tools.seed_calibration import seed_calibration

RUNTIME_DIR = Path(os.getenv(
    "VISION_DEMO_RUNTIME_DIR",
    "/app/runtime/demo" if Path("/app").exists() else "runtime/demo",
))
RUNTIME_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="Retail Edge Vision Demo")
app.mount("/runtime", StaticFiles(directory=str(RUNTIME_DIR)), name="runtime")

_runs: dict[str, dict[str, Any]] = {}
_runs_lock = RLock()


class RunStatus(BaseModel):
    run_id: str
    status: str
    progress: float = 0.0
    cameras: list[str] = Field(default_factory=list)
    artifact_dir: str
    error: str | None = None


UPLOAD_PAGE_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Retail Edge Vision Demo</title>
  <style>
    :root { color-scheme: dark; --bg:#101112; --panel:#181a1b; --line:#303438; --text:#f5f7f8; --muted:#aeb6bd; --accent:#35d07f; }
    * { box-sizing: border-box; }
    body { margin:0; background:var(--bg); color:var(--text); font-family:system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }
    main { max-width:1180px; margin:0 auto; padding:24px; }
    h1 { font-size:24px; margin:0 0 6px; }
    h2 { font-size:16px; margin:0 0 12px; }
    p { color:var(--muted); margin:0; }
    a { color:#8ec5ff; }
    .panel { background:var(--panel); border:1px solid var(--line); padding:16px; margin-top:16px; }
    form { display:grid; gap:14px; grid-template-columns:repeat(auto-fit,minmax(220px,1fr)); }
    label { color:var(--muted); display:grid; gap:7px; font-size:13px; }
    input,button { font:inherit; min-height:42px; }
    input { background:#0d0e0f; border:1px solid var(--line); color:var(--text); padding:9px 10px; width:100%; }
    button { background:var(--accent); border:0; color:#07100b; cursor:pointer; font-weight:800; padding:10px 14px; }
    button.secondary { background:#f5f7f8; color:#111; }
    button:disabled { cursor:wait; opacity:.55; }
    progress { height:12px; margin-top:12px; width:100%; }
    .player { display:none; }
    .video-grid { display:grid; gap:14px; grid-template-columns:repeat(auto-fit,minmax(360px,1fr)); }
    video { aspect-ratio:16/9; background:#000; border:1px solid var(--line); object-fit:contain; width:100%; }
    .metrics { display:grid; gap:8px; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); margin-top:14px; }
    .metric { border:1px solid var(--line); padding:10px; }
    .metric span { color:var(--muted); display:block; font-size:12px; }
    .metric strong { display:block; font-size:20px; margin-top:4px; }
    .controls { align-items:center; display:flex; flex-wrap:wrap; gap:10px; margin:14px 0; }
    .error { color:#ff8f8f; margin-top:10px; }
    @media (max-width:720px) { main { padding:16px; } .video-grid { grid-template-columns:1fr; } }
  </style>
</head>
<body>
  <main>
    <h1>Retail Edge Vision Demo</h1>
    <p>Upload camera videos, run Marji IEP2 + IEP3, then review synced annotated outputs.</p>
    <section class="panel">
      <h2>New Run</h2>
      <form id="form">
        <label>Camera 1 video <input id="camera1" name="camera1" type="file" accept="video/*" required></label>
        <label>Camera 2 video <input id="camera2" name="camera2" type="file" accept="video/*" required></label>
        <label>Sample rate fps <input id="sample_rate_fps" name="sample_rate_fps" type="number" min="0.1" max="30" step="0.1" value="2"></label>
        <label>Batch window seconds <input id="batch_window_seconds" name="batch_window_seconds" type="number" min="1" max="60" step="1" value="2"></label>
        <label>Detector confidence <input id="detector_confidence" name="detector_confidence" type="number" min="0.01" max="1" step="0.01" value="0.55"></label>
        <label>ReID similarity threshold <input id="reid_match_threshold" name="reid_match_threshold" type="number" min="0.01" max="1" step="0.01" value="0.70"></label>
        <button id="run" type="submit">Run processing</button>
      </form>
      <p id="status">Waiting for upload.</p>
      <progress id="progress" value="0" max="1"></progress>
      <p id="error" class="error"></p>
    </section>
    <section id="player" class="panel player">
      <h2>Result</h2>
      <p id="summary"></p>
      <div class="metrics" id="metrics"></div>
      <div class="controls">
        <button id="play" type="button">Play synced</button>
        <button id="pause" class="secondary" type="button">Pause</button>
        <button id="reset" class="secondary" type="button">Reset</button>
        <a id="review" href="#">review page</a>
        <a id="results" href="#">results.json</a>
      </div>
      <div class="video-grid" id="videos"></div>
    </section>
  </main>
<script>
const form = document.getElementById("form");
const runButton = document.getElementById("run");
const statusText = document.getElementById("status");
const progress = document.getElementById("progress");
const errorText = document.getElementById("error");
const player = document.getElementById("player");
const videosRoot = document.getElementById("videos");
let poll = null;
let syncing = false;

function numberField(data, id) {
  const value = document.getElementById(id).value.trim();
  if (value) data.append(id, value);
}

async function pollRun(runId) {
  const res = await fetch(`/runs/${runId}`);
  if (!res.ok) throw new Error("Unable to read run status.");
  const status = await res.json();
  statusText.textContent = `${status.status} · ${Math.round((status.progress || 0) * 100)}%`;
  progress.value = status.progress || 0;
  if (status.status === "failed") throw new Error(status.error || "Processing failed.");
  if (status.status === "complete") {
    clearInterval(poll);
    poll = null;
    await loadResults(runId);
  }
}

async function loadResults(runId) {
  const res = await fetch(`/runs/${runId}/results`);
  if (!res.ok) throw new Error("Results are not ready.");
  const result = await res.json();
  const base = `/runtime/${runId}`;
  document.getElementById("summary").textContent = `Run ${runId} · ${result.identity_count} identities · ${result.track_count} local tracks`;
  document.getElementById("metrics").innerHTML = [
    ["Identities", result.identity_count],
    ["Local tracks", result.track_count],
    ["Global observations", result.global_observation_count],
    ["Local observations", result.local_observation_count],
    ["Batch window", `${result.batch_window_seconds}s`]
  ].map(([k,v]) => `<div class="metric"><span>${k}</span><strong>${v}</strong></div>`).join("");
  videosRoot.innerHTML = result.cameras.map((cam) => `<section><h2>${cam.label}</h2><video class="cam" controls muted playsinline preload="metadata" src="${base}/${cam.annotated_file}"></video></section>`).join("");
  document.getElementById("review").href = `${base}/review.html`;
  document.getElementById("results").href = `${base}/results.json`;
  player.style.display = "block";
  runButton.disabled = false;
  statusText.textContent = "Complete. Videos are ready.";
}

function cams() { return Array.from(document.querySelectorAll("video.cam")); }
function align(master) { for (const v of cams()) if (v !== master && Math.abs(v.currentTime - master.currentTime) > 0.08) v.currentTime = master.currentTime; }
async function playSynced(master = cams()[0]) { if (!master) return; syncing = true; align(master); await Promise.allSettled(cams().map(v => v.play())); syncing = false; }
function pauseSynced(master = cams()[0]) { if (!master) return; syncing = true; align(master); cams().forEach(v => v.pause()); syncing = false; }
function resetSynced() { syncing = true; cams().forEach(v => { v.pause(); v.currentTime = 0; }); syncing = false; }
setInterval(() => { const first = cams()[0]; if (first && !syncing) align(first); }, 250);
document.getElementById("play").onclick = () => playSynced();
document.getElementById("pause").onclick = () => pauseSynced();
document.getElementById("reset").onclick = resetSynced;

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  errorText.textContent = "";
  player.style.display = "none";
  runButton.disabled = true;
  const data = new FormData();
  data.append("camera1", document.getElementById("camera1").files[0]);
  data.append("camera2", document.getElementById("camera2").files[0]);
  numberField(data, "sample_rate_fps");
  numberField(data, "batch_window_seconds");
  numberField(data, "detector_confidence");
  numberField(data, "reid_match_threshold");
  try {
    const res = await fetch("/upload/runs", { method: "POST", body: data });
    if (!res.ok) throw new Error(await res.text());
    const status = await res.json();
    statusText.textContent = `Queued ${status.run_id}`;
    progress.value = 0;
    poll = setInterval(() => pollRun(status.run_id).catch((e) => {
      clearInterval(poll); poll = null; errorText.textContent = e.message; runButton.disabled = false;
    }), 2000);
    await pollRun(status.run_id);
  } catch (e) {
    errorText.textContent = e.message;
    runButton.disabled = false;
  }
});
</script>
</body>
</html>
"""


def _run_dir(run_id: str) -> Path:
    return RUNTIME_DIR / run_id


def _status_path(run_id: str) -> Path:
    return _run_dir(run_id) / "status.json"


def _set_status(run_id: str, patch: dict[str, Any]) -> dict[str, Any]:
    with _runs_lock:
        current = _runs.get(run_id, {
            "run_id": run_id,
            "status": "queued",
            "progress": 0.0,
            "cameras": [],
            "artifact_dir": str(_run_dir(run_id)),
            "error": None,
        })
        current.update(patch)
        _runs[run_id] = current
        write_json_atomic(_status_path(run_id), current)
        return current


def _get_status(run_id: str) -> dict[str, Any]:
    with _runs_lock:
        if run_id in _runs:
            return _runs[run_id]
    path = _status_path(run_id)
    if path.exists():
        data = read_json(path)
        with _runs_lock:
            _runs[run_id] = data
        return data
    raise HTTPException(status_code=404, detail={"error": "Run not found", "code": "RUN_NOT_FOUND"})


async def _save_upload(upload: UploadFile, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("wb") as output:
        while True:
            chunk = await upload.read(1024 * 1024)
            if not chunk:
                break
            output.write(chunk)


def _video_pixels(video_path: Path) -> int:
    import cv2

    cap = cv2.VideoCapture(str(video_path))
    try:
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 1)
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 1)
        return max(1, width * height)
    finally:
        cap.release()


async def _summarize_run(run_id: str, store_id: uuid.UUID, cameras: dict[str, Path], batch_window_seconds: int) -> dict:
    async with session_scope() as session:
        identity_count = (
            await session.execute(
                text("SELECT COUNT(*) FROM global_identities WHERE store_id = :store_id"),
                {"store_id": store_id},
            )
        ).scalar_one()
        global_observation_count = (
            await session.execute(
                text("SELECT COUNT(*) FROM global_tracking_history WHERE store_id = :store_id"),
                {"store_id": store_id},
            )
        ).scalar_one()
        local_observation_count = (
            await session.execute(
                text("SELECT COUNT(*) FROM tracking_history WHERE camera_id IN :camera_ids")
                .bindparams(bindparam("camera_ids", expanding=True)),
                {"camera_ids": list(cameras)},
            )
        ).scalar_one()
        track_count = (
            await session.execute(
                text("SELECT COUNT(DISTINCT local_id) FROM tracking_history WHERE camera_id IN :camera_ids")
                .bindparams(bindparam("camera_ids", expanding=True)),
                {"camera_ids": list(cameras)},
            )
        ).scalar_one()
        gids = (
            await session.execute(
                text("SELECT global_id::text FROM global_identities WHERE store_id = :store_id ORDER BY first_seen_ts"),
                {"store_id": store_id},
            )
        ).scalars().all()

    camera_results = []
    for index, (camera_id, path) in enumerate(cameras.items(), start=1):
        out = _run_dir(run_id) / "annotated" / f"camera{index}.mp4"
        rendered = await render_camera(str(path), camera_id, str(out), start_ms=0, sample_fps=get_settings().sample_rate_fps)
        camera_results.append({
            "camera_id": camera_id,
            "label": f"camera{index}",
            "source_file": str(path),
            "annotated_file": str(Path(rendered).relative_to(_run_dir(run_id))),
        })

    result = {
        "run_id": run_id,
        "store_id": str(store_id),
        "processing_base": "marji_iep2_iep3",
        "batch_window_seconds": batch_window_seconds,
        "identity_count": identity_count,
        "track_count": track_count,
        "local_observation_count": local_observation_count,
        "global_observation_count": global_observation_count,
        "global_ids": gids,
        "cameras": camera_results,
    }
    write_json_atomic(_run_dir(run_id) / "results.json", result)
    render_review_page(
        _run_dir(run_id) / "review.html",
        [{"camera_id": c["label"], "video_src": c["annotated_file"]} for c in camera_results],
        {
            "identities": identity_count,
            "local_tracks": track_count,
            "local_observations": local_observation_count,
            "global_observations": global_observation_count,
        },
        gids,
    )
    return result


def _run_uploaded(run_id: str, store_id: uuid.UUID, cameras: dict[str, Path], settings_patch: dict[str, Any]) -> None:
    try:
        async def _go() -> None:
            await apply_schema()
            settings = get_settings()
            for key, value in settings_patch.items():
                setattr(settings, key, value)
            await seed_calibration(store_id, list(cameras))
            calibrations = await load_calibrations(list(cameras))
            frame_px = {cam: _video_pixels(path) for cam, path in cameras.items()}
            _set_status(run_id, {"status": "running", "progress": 0.15})
            await run(RunPlan(store_id, {cam: str(path) for cam, path in cameras.items()}, frame_px), calibrations, settings=settings, start_ms=0)
            _set_status(run_id, {"status": "rendering", "progress": 0.8})
            result = await _summarize_run(run_id, store_id, cameras, settings.batch_window_seconds)
            _set_status(run_id, {
                "status": "complete",
                "progress": 1.0,
                "cameras": [c["label"] for c in result["cameras"]],
                "error": None,
            })

        asyncio.run(_go())
    except Exception as exc:
        _set_status(run_id, {"status": "failed", "progress": 1.0, "error": str(exc)})


@app.get("/health")
async def health():
    return {"service": "vision-demo", "status": "ok"}


@app.get("/", response_class=HTMLResponse)
async def home():
    return HTMLResponse(UPLOAD_PAGE_HTML)


@app.post("/upload/runs", response_model=RunStatus)
async def start_upload_run(
    background_tasks: BackgroundTasks,
    camera1: UploadFile = File(...),
    camera2: UploadFile = File(...),
    sample_rate_fps: float = Form(2.0),
    batch_window_seconds: int = Form(2),
    detector_confidence: float = Form(0.55),
    reid_match_threshold: float = Form(0.70),
):
    run_id = uuid.uuid4().hex
    store_id = uuid.uuid4()
    run_root = _run_dir(run_id)
    cam_ids = {
        f"camera1-{run_id[:8]}": run_root / "uploads" / "camera1.mp4",
        f"camera2-{run_id[:8]}": run_root / "uploads" / "camera2.mp4",
    }
    await _save_upload(camera1, list(cam_ids.values())[0])
    await _save_upload(camera2, list(cam_ids.values())[1])
    status = _set_status(run_id, {
        "status": "queued",
        "progress": 0.0,
        "cameras": ["camera1", "camera2"],
        "artifact_dir": str(run_root),
        "error": None,
    })
    background_tasks.add_task(
        _run_uploaded,
        run_id,
        store_id,
        cam_ids,
        {
            "sample_rate_fps": sample_rate_fps,
            "batch_window_seconds": batch_window_seconds,
            "detector_confidence": detector_confidence,
            "reid_match_threshold": reid_match_threshold,
        },
    )
    return RunStatus(**status)


@app.get("/runs/{run_id}", response_model=RunStatus)
async def get_run(run_id: str):
    return RunStatus(**_get_status(run_id))


@app.get("/runs/{run_id}/results")
async def get_results(run_id: str):
    _get_status(run_id)
    path = _run_dir(run_id) / "results.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail={"error": "Results not ready", "code": "RESULTS_NOT_READY"})
    return JSONResponse(read_json(path))
