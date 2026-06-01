from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path
from threading import RLock
from typing import Any

from fastapi import BackgroundTasks, FastAPI
from pydantic import BaseModel, Field

from .bus import create_event_producer
from .eep_client import EepClient
from .live import LiveStreamRunRequest, cameras_from_topology, publish_live_streams
from .simulator import publish_test1_frames

app = FastAPI(title="IEP1 — Ingestion")

_runs: dict[str, dict[str, Any]] = {}
_runs_lock = RLock()
_startup_tasks: set[asyncio.Task] = set()


class Test1SimulatorRunRequest(BaseModel):
    test1_dir: str = "/app/testing-data/Test1"
    store_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    version_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    section_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    sample_rate_fps: float = Field(2.0, gt=0, le=30)
    max_frames_per_camera: int | None = Field(None, gt=0, le=100000)
    realtime: bool = False


def _set_run(run_id: str, patch: dict[str, Any]) -> dict[str, Any]:
    with _runs_lock:
        current = _runs.get(run_id, {
            "run_id": run_id,
            "status": "queued",
            "progress": 0.0,
            "frames_expected": None,
            "frames_published": 0,
            "cameras": [],
            "error": None,
        })
        current.update(patch)
        _runs[run_id] = current
        return current


def _run_test1_simulator(run_id: str, request: Test1SimulatorRunRequest) -> None:
    import asyncio

    try:
        if not Path(request.test1_dir).exists():
            raise RuntimeError(f"Test1 directory not found: {request.test1_dir}")
        status = _set_run(run_id, {"status": "running"})
        asyncio.run(
            publish_test1_frames(
                create_event_producer(),
                test1_dir=request.test1_dir,
                store_id=request.store_id,
                version_id=request.version_id,
                section_id=request.section_id,
                sample_rate_fps=request.sample_rate_fps,
                max_frames_per_camera=request.max_frames_per_camera,
                realtime=request.realtime,
                status=status,
            )
        )
    except Exception as exc:
        _set_run(run_id, {"status": "failed", "progress": 1.0, "error": str(exc)})


def _run_live_streams(run_id: str, request: LiveStreamRunRequest) -> None:
    import asyncio

    try:
        status = _set_run(run_id, {"status": "running"})
        asyncio.run(
            publish_live_streams(
                create_event_producer(),
                EepClient(),
                run_id=run_id,
                request=request,
                status=status,
            )
        )
    except Exception as exc:
        _set_run(run_id, {"status": "failed", "progress": 1.0, "error": str(exc)})


async def _run_store_topology_streams_async(
    run_id: str, store_id: uuid.UUID, sample_rate_fps: float, max_frames_per_camera: int | None
) -> None:
    try:
        eep_client = EepClient()
        topology = await eep_client.load_topology(store_id)
        request = cameras_from_topology(topology)
        request.sample_rate_fps = sample_rate_fps
        request.max_frames_per_camera = max_frames_per_camera
        status = _set_run(run_id, {"status": "running", "version_id": str(request.version_id)})
        await publish_live_streams(
            create_event_producer(),
            eep_client,
            run_id=run_id,
            request=request,
            status=status,
        )
    except Exception as exc:
        _set_run(run_id, {"status": "failed", "progress": 1.0, "error": str(exc)})


def _run_store_topology_streams(
    run_id: str, store_id: uuid.UUID, sample_rate_fps: float, max_frames_per_camera: int | None
) -> None:
    asyncio.run(_run_store_topology_streams_async(run_id, store_id, sample_rate_fps, max_frames_per_camera))


def _optional_int_env(name: str) -> int | None:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return None
    return int(raw)


@app.on_event("startup")
async def auto_start_store_topology_run() -> None:
    raw_store_id = os.getenv("IEP1_AUTO_START_STORE_ID")
    if not raw_store_id:
        return

    run_id = os.getenv("IEP1_AUTO_START_RUN_ID") or f"edge-{uuid.uuid4().hex}"
    store_id = uuid.UUID(raw_store_id)
    sample_rate_fps = float(os.getenv("IEP1_AUTO_START_SAMPLE_RATE_FPS", "2.0"))
    max_frames_per_camera = _optional_int_env("IEP1_AUTO_START_MAX_FRAMES_PER_CAMERA")
    _set_run(run_id, {"status": "queued", "store_id": str(store_id), "error": None})
    task = asyncio.create_task(
        _run_store_topology_streams_async(run_id, store_id, sample_rate_fps, max_frames_per_camera)
    )
    _startup_tasks.add(task)
    task.add_done_callback(_startup_tasks.discard)


@app.get("/health")
async def health():
    return {"service": "iep1-ingestion", "status": "ok"}


@app.post("/simulators/test1/runs")
async def start_test1_simulator(request: Test1SimulatorRunRequest, background_tasks: BackgroundTasks):
    run_id = uuid.uuid4().hex
    status = _set_run(run_id, {"status": "queued", "error": None})
    background_tasks.add_task(_run_test1_simulator, run_id, request)
    return status


@app.post("/streams/runs")
async def start_live_stream_run(request: LiveStreamRunRequest, background_tasks: BackgroundTasks):
    run_id = uuid.uuid4().hex
    status = _set_run(run_id, {"status": "queued", "error": None})
    background_tasks.add_task(_run_live_streams, run_id, request)
    return status


@app.post("/stores/{store_id}/streams/runs")
async def start_store_topology_stream_run(
    store_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    sample_rate_fps: float = 2.0,
    max_frames_per_camera: int | None = None,
):
    run_id = uuid.uuid4().hex
    status = _set_run(run_id, {"status": "queued", "store_id": str(store_id), "error": None})
    background_tasks.add_task(_run_store_topology_streams, run_id, store_id, sample_rate_fps, max_frames_per_camera)
    return status


@app.get("/simulators/runs/{run_id}")
async def get_simulator_run(run_id: str):
    return _get_run(run_id)


@app.get("/runs/{run_id}")
async def get_run(run_id: str):
    return _get_run(run_id)


def _get_run(run_id: str) -> dict[str, Any]:
    with _runs_lock:
        if run_id in _runs:
            return _runs[run_id]
    return {"run_id": run_id, "status": "not_found", "error": "Run not found"}
