from __future__ import annotations

import uuid
from pathlib import Path
from threading import RLock
from typing import Any

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.runner import execute_test1_run
from app.schemas import RunArtifactsResponse, RunStatusResponse, Test1RunRequest
from app.storage import RUNTIME_DIR, ensure_runtime_dir, read_json, run_dir, write_json

app = FastAPI(title="IEP2 — Vision")

ensure_runtime_dir()
app.mount("/runtime", StaticFiles(directory=str(RUNTIME_DIR)), name="runtime")

_runs: dict[str, dict[str, Any]] = {}
_runs_lock = RLock()


UPLOAD_PAGE_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>IEP2 Vision Upload</title>
  <style>
    :root {
      color-scheme: dark;
      --bg: #101112;
      --panel: #181a1b;
      --line: #303438;
      --text: #f5f7f8;
      --muted: #aeb6bd;
      --accent: #35d07f;
      --warn: #ffbf47;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    main { max-width: 1240px; margin: 0 auto; padding: 24px; }
    h1 { font-size: 24px; line-height: 1.15; margin: 0 0 6px; }
    h2 { font-size: 16px; margin: 0 0 12px; }
    p { color: var(--muted); margin: 0; }
    a { color: #8ec5ff; }
    .topbar {
      align-items: end;
      display: flex;
      justify-content: space-between;
      gap: 16px;
      margin-bottom: 18px;
    }
    .panel {
      background: var(--panel);
      border: 1px solid var(--line);
      padding: 16px;
    }
    form {
      display: grid;
      gap: 14px;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
    }
    label { color: var(--muted); display: grid; gap: 7px; font-size: 13px; }
    input, button {
      border-radius: 0;
      font: inherit;
      min-height: 42px;
    }
    input {
      background: #0d0e0f;
      border: 1px solid var(--line);
      color: var(--text);
      padding: 9px 10px;
      width: 100%;
    }
    input[type="file"] { padding: 8px; }
    button {
      background: var(--accent);
      border: 0;
      color: #07100b;
      cursor: pointer;
      font-weight: 800;
      padding: 10px 14px;
    }
    button.secondary { background: #f5f7f8; color: #111; }
    button:disabled { cursor: wait; opacity: .55; }
    .actions { align-items: end; display: flex; gap: 10px; }
    .status {
      display: grid;
      gap: 10px;
      margin: 16px 0;
    }
    progress {
      appearance: none;
      height: 12px;
      width: 100%;
    }
    progress::-webkit-progress-bar { background: #0d0e0f; border: 1px solid var(--line); }
    progress::-webkit-progress-value { background: var(--accent); }
    .metrics {
      display: grid;
      gap: 8px;
      grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
      margin-top: 14px;
    }
    .metric {
      border: 1px solid var(--line);
      padding: 10px;
    }
    .metric span { color: var(--muted); display: block; font-size: 12px; }
    .metric strong { display: block; font-size: 20px; margin-top: 4px; }
    .player { display: none; margin-top: 18px; }
    .sync-controls {
      align-items: center;
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin: 14px 0;
    }
    .video-grid {
      display: grid;
      gap: 14px;
      grid-template-columns: repeat(auto-fit, minmax(360px, 1fr));
    }
    video {
      aspect-ratio: 16 / 9;
      background: #000;
      border: 1px solid var(--line);
      object-fit: contain;
      width: 100%;
    }
    .error { color: #ff8f8f; }
    .hint { color: var(--warn); }
    @media (max-width: 720px) {
      main { padding: 16px; }
      .topbar { align-items: start; flex-direction: column; }
      .video-grid { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <main>
    <div class="topbar">
      <div>
        <h1>IEP2 Vision Processor</h1>
        <p>Upload two camera videos, run synchronized tracking/ReID, then review both outputs together.</p>
      </div>
      <a href="/health">health</a>
    </div>

    <section class="panel">
      <h2>New Run</h2>
      <form id="upload-form">
        <label>Camera 1 video
          <input id="camera1" name="camera1" type="file" accept="video/*" required>
        </label>
        <label>Camera 2 video
          <input id="camera2" name="camera2" type="file" accept="video/*" required>
        </label>
        <label>Sample rate fps
          <input id="sample_rate_fps" name="sample_rate_fps" type="number" min="0.1" max="30" step="0.1" value="2">
        </label>
        <label>Frame cap per camera
          <input id="max_frames_per_camera" name="max_frames_per_camera" type="number" min="1" max="100000" placeholder="blank = full video">
        </label>
        <label>Detection confidence
          <input id="confidence_threshold" name="confidence_threshold" type="number" min="0.01" max="1" step="0.01" value="0.55">
        </label>
        <label>ReID distance threshold
          <input id="match_threshold" name="match_threshold" type="number" min="0.01" max="1.99" step="0.01" value="0.3">
        </label>
        <div class="actions">
          <button id="run-button" type="submit">Run processing</button>
        </div>
      </form>
    </section>

    <section class="status">
      <p id="status-text">Waiting for upload.</p>
      <progress id="progress" value="0" max="1"></progress>
      <p id="error-text" class="error"></p>
    </section>

    <section id="player" class="player">
      <div class="panel">
        <h2>Result</h2>
        <p id="result-summary"></p>
        <div class="metrics" id="metrics"></div>
        <div class="sync-controls">
          <button id="play-sync" type="button">Play synced</button>
          <button id="pause-sync" class="secondary" type="button">Pause</button>
          <button id="reset-sync" class="secondary" type="button">Reset</button>
          <span id="sync-status">Synced timeline</span>
        </div>
        <div class="video-grid">
          <section>
            <h2>camera1</h2>
            <video id="video-camera1" controls preload="metadata" playsinline muted></video>
          </section>
          <section>
            <h2>camera2</h2>
            <video id="video-camera2" controls preload="metadata" playsinline muted></video>
          </section>
        </div>
        <p style="margin-top: 12px;">
          <a id="review-link" href="#">review page</a> ·
          <a id="results-link" href="#">results.json</a> ·
          <a id="gallery-link" href="#">identity_gallery.json</a>
        </p>
      </div>
    </section>
  </main>

  <script>
    const form = document.getElementById("upload-form");
    const runButton = document.getElementById("run-button");
    const statusText = document.getElementById("status-text");
    const errorText = document.getElementById("error-text");
    const progress = document.getElementById("progress");
    const player = document.getElementById("player");
    const metrics = document.getElementById("metrics");
    const resultSummary = document.getElementById("result-summary");
    const videos = [
      document.getElementById("video-camera1"),
      document.getElementById("video-camera2")
    ];
    let activeRunId = null;
    let pollingHandle = null;
    let syncing = false;

    function setStatus(message, value = null) {
      statusText.textContent = message;
      if (value !== null) progress.value = value;
    }

    function appendNumber(formData, id) {
      const input = document.getElementById(id);
      if (input.value.trim() !== "") formData.append(id, input.value.trim());
    }

    async function pollRun(runId) {
      const response = await fetch(`/mock/test1/runs/${runId}`);
      if (!response.ok) throw new Error("Unable to read run status.");
      const status = await response.json();
      const percent = Math.round((status.progress || 0) * 100);
      setStatus(`${status.status} · ${percent}% · frames ${status.frames_processed}/${status.frames_expected ?? "?"} · identities ${status.identities}`, status.progress || 0);

      if (status.status === "failed") {
        throw new Error(status.error || "Processing failed.");
      }
      if (status.status === "complete") {
        clearInterval(pollingHandle);
        pollingHandle = null;
        await loadResults(runId);
      }
    }

    async function loadResults(runId) {
      const response = await fetch(`/mock/test1/runs/${runId}/results`);
      if (!response.ok) throw new Error("Results are not ready.");
      const result = await response.json();
      const base = `/runtime/${runId}`;

      videos[0].src = `${base}/annotated/camera1.mp4`;
      videos[1].src = `${base}/annotated/camera2.mp4`;
      for (const video of videos) video.load();

      resultSummary.textContent = `Run ${runId} · ${result.processing_mode} · ${result.timeline_frames} synced frames at ${result.timeline_fps} fps`;
      metrics.innerHTML = [
        ["Identities", result.identity_count],
        ["Tracks", result.track_count],
        ["Observations", result.observation_count],
        ["Cross-camera ReID", result.identity_match_counts?.cross_camera_reid ?? 0],
        ["Identity merges", result.identity_match_counts?.identity_merged ?? 0],
        ["Gallery size", result.identity_gallery_size]
      ].map(([label, value]) => `<div class="metric"><span>${label}</span><strong>${value}</strong></div>`).join("");

      document.getElementById("review-link").href = `${base}/review.html`;
      document.getElementById("results-link").href = `${base}/results.json`;
      document.getElementById("gallery-link").href = `${base}/identity_gallery.json`;
      player.style.display = "block";
      setStatus("Complete. Videos are ready.", 1);
      runButton.disabled = false;
    }

    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      errorText.textContent = "";
      player.style.display = "none";
      runButton.disabled = true;
      setStatus("Uploading videos...", 0);

      const formData = new FormData();
      formData.append("camera1", document.getElementById("camera1").files[0]);
      formData.append("camera2", document.getElementById("camera2").files[0]);
      appendNumber(formData, "sample_rate_fps");
      appendNumber(formData, "max_frames_per_camera");
      appendNumber(formData, "confidence_threshold");
      appendNumber(formData, "match_threshold");

      try {
        const response = await fetch("/upload/runs", { method: "POST", body: formData });
        if (!response.ok) {
          const text = await response.text();
          throw new Error(text || "Upload failed.");
        }
        const status = await response.json();
        activeRunId = status.run_id;
        setStatus(`Queued run ${activeRunId}`, 0);
        if (pollingHandle) clearInterval(pollingHandle);
        pollingHandle = setInterval(() => {
          pollRun(activeRunId).catch((error) => {
            clearInterval(pollingHandle);
            pollingHandle = null;
            errorText.textContent = error.message;
            runButton.disabled = false;
          });
        }, 2000);
        await pollRun(activeRunId);
      } catch (error) {
        errorText.textContent = error.message;
        runButton.disabled = false;
      }
    });

    function alignTo(master) {
      for (const video of videos) {
        if (video === master) continue;
        if (Math.abs(video.currentTime - master.currentTime) > 0.08) {
          video.currentTime = master.currentTime;
        }
      }
    }

    async function playSynced(master = videos[0]) {
      syncing = true;
      alignTo(master);
      await Promise.allSettled(videos.map((video) => video.play()));
      syncing = false;
      document.getElementById("sync-status").textContent = `Synced at ${master.currentTime.toFixed(2)}s`;
    }

    function pauseSynced(master = videos[0]) {
      syncing = true;
      alignTo(master);
      videos.forEach((video) => video.pause());
      syncing = false;
      document.getElementById("sync-status").textContent = `Paused at ${master.currentTime.toFixed(2)}s`;
    }

    function resetSynced() {
      syncing = true;
      videos.forEach((video) => {
        video.pause();
        video.currentTime = 0;
      });
      syncing = false;
      document.getElementById("sync-status").textContent = "Synced timeline";
    }

    for (const video of videos) {
      video.addEventListener("play", () => {
        if (!syncing) playSynced(video);
      });
      video.addEventListener("pause", () => {
        if (!syncing && !videos.every((item) => item.paused)) pauseSynced(video);
      });
      video.addEventListener("seeking", () => {
        if (!syncing) {
          syncing = true;
          alignTo(video);
          syncing = false;
        }
      });
      video.addEventListener("timeupdate", () => {
        if (!syncing) alignTo(video);
      });
    }

    document.getElementById("play-sync").addEventListener("click", () => playSynced());
    document.getElementById("pause-sync").addEventListener("click", () => pauseSynced());
    document.getElementById("reset-sync").addEventListener("click", resetSynced);
  </script>
</body>
</html>
"""


@app.get("/health")
async def health():
    return {"service": "iep2-vision", "status": "ok"}


@app.get("/", response_class=HTMLResponse)
async def upload_page():
    return HTMLResponse(UPLOAD_PAGE_HTML)


def _status_path(run_id: str) -> Path:
    return run_dir(run_id) / "status.json"


def _set_status(run_id: str, patch: dict[str, Any]) -> dict[str, Any]:
    with _runs_lock:
        current = _runs.get(run_id, {
            "run_id": run_id,
            "status": "queued",
            "progress": 0.0,
            "frames_processed": 0,
            "frames_expected": None,
            "observations": 0,
            "identities": 0,
            "cameras": [],
            "error": None,
            "artifact_dir": str(run_dir(run_id)),
        })
        current.update(patch)
        _runs[run_id] = current
        write_json(_status_path(run_id), current)
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


def _run_test1(run_id: str, request: Test1RunRequest) -> None:
    try:
        execute_test1_run(run_id, request, lambda patch: _set_status(run_id, patch))
    except Exception as exc:
        _set_status(run_id, {
            "status": "failed",
            "error": str(exc),
            "progress": 1.0,
        })


async def _save_upload(upload: UploadFile, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("wb") as output:
        while True:
            chunk = await upload.read(1024 * 1024)
            if not chunk:
                break
            output.write(chunk)


@app.post("/upload/runs", response_model=RunStatusResponse)
async def start_uploaded_run(
    background_tasks: BackgroundTasks,
    camera1: UploadFile = File(...),
    camera2: UploadFile = File(...),
    sample_rate_fps: float = Form(2.0),
    max_frames_per_camera: int | None = Form(None),
    confidence_threshold: float = Form(0.55),
    match_threshold: float = Form(0.3),
    identity_gallery_size: int = Form(6),
):
    run_id = uuid.uuid4().hex
    upload_dir = run_dir(run_id) / "uploads" / "Test1"
    await _save_upload(camera1, upload_dir / "Camera1.mp4")
    await _save_upload(camera2, upload_dir / "Camera2.mp4")

    request = Test1RunRequest(
        sample_rate_fps=sample_rate_fps,
        max_frames_per_camera=max_frames_per_camera,
        confidence_threshold=confidence_threshold,
        match_threshold=match_threshold,
        identity_gallery_size=identity_gallery_size,
        test1_dir=str(upload_dir),
    )
    frames_expected = None if request.max_frames_per_camera is None else request.max_frames_per_camera * 2
    status = _set_status(run_id, {
        "status": "queued",
        "progress": 0.0,
        "frames_processed": 0,
        "frames_expected": frames_expected,
        "observations": 0,
        "identities": 0,
        "cameras": ["camera1", "camera2"],
        "error": None,
        "artifact_dir": str(run_dir(run_id)),
    })
    background_tasks.add_task(_run_test1, run_id, request)
    return RunStatusResponse(**status)


@app.post("/mock/test1/runs", response_model=RunStatusResponse)
async def start_test1_run(request: Test1RunRequest, background_tasks: BackgroundTasks):
    run_id = uuid.uuid4().hex
    frames_expected = None if request.max_frames_per_camera is None else request.max_frames_per_camera * 2
    status = _set_status(run_id, {
        "status": "queued",
        "progress": 0.0,
        "frames_processed": 0,
        "frames_expected": frames_expected,
        "observations": 0,
        "identities": 0,
        "cameras": ["camera1", "camera2"],
        "error": None,
        "artifact_dir": str(run_dir(run_id)),
    })
    background_tasks.add_task(_run_test1, run_id, request)
    return RunStatusResponse(**status)


@app.get("/mock/test1/runs/{run_id}", response_model=RunStatusResponse)
async def get_test1_run(run_id: str):
    return RunStatusResponse(**_get_status(run_id))


@app.get("/mock/test1/runs/{run_id}/results")
async def get_test1_results(run_id: str):
    _get_status(run_id)
    path = run_dir(run_id) / "results.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail={"error": "Results not ready", "code": "RESULTS_NOT_READY"})
    return JSONResponse(read_json(path))


@app.get("/mock/test1/runs/{run_id}/artifacts", response_model=RunArtifactsResponse)
async def get_test1_artifacts(run_id: str):
    _get_status(run_id)
    root = run_dir(run_id)
    files = []
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        rel = path.relative_to(RUNTIME_DIR)
        files.append({
            "path": str(path),
            "relative_path": str(rel),
            "url": f"/runtime/{rel.as_posix()}",
            "size_bytes": path.stat().st_size,
        })
    return RunArtifactsResponse(run_id=run_id, artifact_dir=str(root), files=files)
