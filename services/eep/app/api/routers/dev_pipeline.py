"""DEBUG_MODE-only end-to-end dev pipeline control.

Drives the real IEP1 → IEP2 → IEP3 pipeline from the dev screen without k3s:
  - start/stop both cameras in parallel using the stream URLs in store config
  - expose recent tracking_history (per camera) and global_tracking_history (IEP3)
    rows for the dev tables

Registered only when settings.DEBUG_MODE is true (see app/api/__init__.py).
Never mounted in production.
"""
import asyncio
import json
import logging
import os

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db, AsyncSessionLocal
from app.core import dev_orchestrator as orch

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/debug/dev", tags=["dev-pipeline"])

_DB_URL_SERVER = os.environ.get("DATABASE_URL_SERVER", "")
_REDIS_URL = os.environ.get("SERVER_REDIS_URL") or os.environ.get("REDIS_URL", "redis://redis:6379/0")
_DEVICE_KEY = "inference:device"


class PipelineStartRequest(BaseModel):
    store_id: str
    camera_ids: list[str]
    target_fps: float = 5.0          # sample 5 fps across real-time footage
    window_seconds: float = 60.0
    device: str = "cpu"              # "cpu" | "gpu" — chosen via the dev-screen toggle


async def _read_gpu_status() -> dict:
    """Read GPU capability published by the detector + ReID services to Redis.

    A machine "has a GPU" only if BOTH inference services report a usable GPU
    backend (cuda or xpu) — both run inference, and on one host they agree.
    """
    r = aioredis.from_url(_REDIS_URL)
    try:
        out = {}
        for role in ("detector", "reid"):
            raw = await r.get(f"inference:capability:{role}")
            out[role] = json.loads(raw) if raw else None
    finally:
        await r.aclose()
    det = out.get("detector") or {}
    reid = out.get("reid") or {}
    det_gpu = bool(det.get("cuda") or det.get("xpu"))
    reid_gpu = bool(reid.get("cuda") or reid.get("xpu"))
    return {
        "gpu_available": det_gpu and reid_gpu,
        "detector": det or None,
        "reid": reid or None,
    }


async def _set_inference_device(device: str) -> None:
    """Publish the desired device for the inference services to pick up (~2 s)."""
    r = aioredis.from_url(_REDIS_URL)
    try:
        await r.set(_DEVICE_KEY, device)
    finally:
        await r.aclose()


@router.get("/gpu-status")
async def gpu_status():
    """Report whether this machine exposes a usable GPU to the inference services."""
    return await _read_gpu_status()


class PipelineStopRequest(BaseModel):
    store_id: str
    camera_ids: list[str]


async def _lookup_camera(db: AsyncSession, store_id: str, camera_id: str) -> dict:
    """Return {cloud_stream_url, camera_config_id} for a camera in the active version."""
    row = (await db.execute(
        text("""
            SELECT pc.cloud_stream_url AS url, cc.id::text AS config_id
            FROM physical_cameras pc
            JOIN camera_configs cc ON cc.physical_camera_id = pc.id
            JOIN store_config_versions v ON v.id = cc.version_id
            WHERE pc.id = :cam AND pc.store_id = :store AND v.status = 'active'
            LIMIT 1
        """),
        {"cam": camera_id, "store": store_id},
    )).first()
    if row is None:
        raise HTTPException(
            status_code=404,
            detail=f"Camera {camera_id} not found in active config for store {store_id}",
        )
    if not row.url:
        raise HTTPException(
            status_code=422,
            detail=f"Camera {camera_id} has no stream URL (cloud_stream_url is empty)",
        )
    return {"url": row.url, "config_id": row.config_id}


async def _open_runtime_session(
    db: AsyncSession, store_id: str, camera_id: str, camera_config_id: str
) -> None:
    """Close any open session for this camera, then open a new one.

    IEP3 reads camera_runtime_sessions to resolve camera_config_id for floor
    position scoring; without an open row it falls back to default resolution.
    """
    await db.execute(
        text("""
            UPDATE camera_runtime_sessions
            SET stopped_at = now(), stop_reason = 'manual'
            WHERE physical_camera_id = :cam AND stopped_at IS NULL
        """),
        {"cam": camera_id},
    )
    await db.execute(
        text("""
            INSERT INTO camera_runtime_sessions
                (physical_camera_id, store_id, camera_config_id, started_at)
            VALUES (:cam, :store, :config, now())
        """),
        {"cam": camera_id, "store": store_id, "config": camera_config_id},
    )
    await db.commit()


async def _start_one(body: PipelineStartRequest, camera_id: str) -> dict:
    """Start one camera end-to-end. Uses its own DB session so cameras can be
    started concurrently (a single AsyncSession is not safe across tasks)."""
    loop = asyncio.get_running_loop()
    try:
        async with AsyncSessionLocal() as db:
            cam = await _lookup_camera(db, body.store_id, camera_id)

            # 1) IEP1 AddCamera (blocking gRPC → executor)
            success, err = await loop.run_in_executor(
                None, orch.iep1_add_camera,
                camera_id, cam["url"], body.store_id, body.target_fps, body.window_seconds,
            )
            if not success:
                return {"camera_id": camera_id, "ok": False, "stage": "iep1_add_camera", "error": err}

            # 2) record runtime session so IEP3 can resolve config
            await _open_runtime_session(db, body.store_id, camera_id, cam["config_id"])

        # 3) spawn IEP2 container (blocking docker → executor)
        container = await loop.run_in_executor(
            None, orch.start_iep2,
            body.store_id, camera_id, cam["config_id"], _DB_URL_SERVER, body.window_seconds,
        )
        return {"camera_id": camera_id, "ok": True, "stream_url": cam["url"], "iep2_container": container}
    except HTTPException as exc:
        return {"camera_id": camera_id, "ok": False, "stage": "lookup", "error": str(exc.detail)}
    except Exception as exc:
        return {"camera_id": camera_id, "ok": False, "stage": "start_iep2", "error": str(exc)}


_TRACK_TABLES = (
    "tracking_history",
    "local_centroids",
    "global_identities",
    "global_local_mapping",
    "global_embeddings",
    "global_tracking_history",
    "camera_runtime_sessions",
)


async def _reset_pipeline() -> None:
    """Fresh restart: stop everything, wipe all track tables + Redis, restart IEP3.

    After this, IEP1 cameras are re-added (file replays from frame 1), fresh IEP2
    containers are spawned, and IEP3 starts with empty state — so each Start
    begins a clean run from frame 1.
    """
    loop = asyncio.get_running_loop()

    # 1) tear down any running pipeline
    await loop.run_in_executor(None, orch.iep1_remove_all)
    await loop.run_in_executor(None, orch.stop_all_iep2_dev)

    # 2) truncate all track tables (RESTART IDENTITY resets serial PKs)
    async with AsyncSessionLocal() as db:
        await db.execute(text(
            "TRUNCATE " + ", ".join(_TRACK_TABLES) + " RESTART IDENTITY CASCADE"
        ))
        await db.commit()

    # 3) flush Redis streams + local-id counters
    await loop.run_in_executor(None, orch.flush_pipeline_redis)

    # 4) restart IEP3 for a clean coordinator state, give it a moment to come up
    await loop.run_in_executor(None, orch.restart_iep3)
    await asyncio.sleep(3)


@router.post("/pipeline/start")
async def pipeline_start(body: PipelineStartRequest):
    if not body.camera_ids:
        raise HTTPException(status_code=400, detail="camera_ids must not be empty")

    # Resolve the CPU/GPU choice before anything else.
    want = (body.device or "cpu").lower()
    if want in ("gpu", "cuda", "xpu", "auto"):
        status = await _read_gpu_status()
        if not status["gpu_available"]:
            raise HTTPException(
                status_code=400,
                detail={"error": "This machine has no usable GPU for inference",
                        "code": "NO_GPU", "gpu_status": status},
            )
        await _set_inference_device(want)
    else:
        await _set_inference_device("cpu")

    # Every Start does a full fresh reset first → run begins from frame 1.
    # The reset includes a short wait, by which time the inference services
    # (watcher polls every 2 s) have applied the requested device.
    await _reset_pipeline()
    # Start all cameras in parallel — each task owns its own DB session.
    results = await asyncio.gather(*[_start_one(body, cid) for cid in body.camera_ids])
    all_ok = all(r["ok"] for r in results)
    return {"status": "started" if all_ok else "partial", "cameras": results, "device": want}


async def _stop_one(store_id: str, camera_id: str) -> dict:
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, orch.iep1_remove_camera, camera_id)
    await loop.run_in_executor(None, orch.stop_iep2, store_id, camera_id)
    async with AsyncSessionLocal() as db:
        await db.execute(
            text("""
                UPDATE camera_runtime_sessions
                SET stopped_at = now(), stop_reason = 'manual'
                WHERE physical_camera_id = :cam AND stopped_at IS NULL
            """),
            {"cam": camera_id},
        )
        await db.commit()
    return {"camera_id": camera_id, "ok": True}


@router.post("/pipeline/stop")
async def pipeline_stop(body: PipelineStopRequest):
    results = await asyncio.gather(*[_stop_one(body.store_id, cid) for cid in body.camera_ids])
    return {"status": "stopped", "cameras": results}


@router.get("/tracking")
async def get_tracking(
    camera_id: str = Query(...),
    limit: int = Query(50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    """Recent tracking_history rows for one camera (newest first)."""
    rows = (await db.execute(
        text("""
            SELECT local_id::text AS local_id, timestamp_ms,
                   floor_x, floor_y, zone_id::text AS zone_id,
                   bbox_confidence, bbox_area
            FROM tracking_history
            WHERE camera_id = :cam
            ORDER BY timestamp_ms DESC
            LIMIT :lim
        """),
        {"cam": camera_id, "lim": limit},
    )).mappings().all()
    total = (await db.execute(
        text("SELECT COUNT(*) FROM tracking_history WHERE camera_id = :cam"),
        {"cam": camera_id},
    )).scalar_one()
    return {"camera_id": camera_id, "total": total, "rows": [dict(r) for r in rows]}


@router.get("/iep3")
async def get_iep3(
    store_id: str = Query(...),
    limit: int = Query(50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    """Recent global_tracking_history (IEP3 reconciliation output), newest first."""
    rows = (await db.execute(
        text("""
            SELECT global_id::text AS global_id, batch_number, timestamp_ms,
                   floor_x, floor_y, zone_id::text AS zone_id,
                   source_camera, selection_score
            FROM global_tracking_history
            WHERE store_id = :store
            ORDER BY timestamp_ms DESC
            LIMIT :lim
        """),
        {"store": store_id, "lim": limit},
    )).mappings().all()
    summary = (await db.execute(
        text("""
            SELECT COUNT(*) AS positions,
                   COUNT(DISTINCT global_id) AS unique_globals,
                   COUNT(DISTINCT source_camera) AS cameras
            FROM global_tracking_history WHERE store_id = :store
        """),
        {"store": store_id},
    )).mappings().first()
    return {"store_id": store_id, "summary": dict(summary), "rows": [dict(r) for r in rows]}
