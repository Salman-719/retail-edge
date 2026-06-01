"""HTTP persistence adapter — sends tracking batches to EEP instead of
writing directly to Postgres.

Implements the same PersistencePort interface as PostgresPersistence so
Iep2Runtime needs no changes; swap is done in runtime.setup() by checking
whether EEP_BASE_URL is configured.

Embeddings and centroids are queued locally and flushed together with
positions in one HTTP call, matching the 2-second batch window.
"""
from __future__ import annotations

import uuid
from time import monotonic
from typing import Any

import httpx
import numpy as np

from common.config import get_settings


class EepHttpPersistence:
    def __init__(self, store_id: str, settings=None):
        self._s = settings or get_settings()
        self._store_id = store_id
        self._pos_buffer: list[dict] = []
        self._emb_buffer: list[dict] = []
        self._cen_buffer: list[dict] = []
        self._last_flush = monotonic()

    # ── PersistencePort interface ─────────────────────────────────────────────

    def append_position(
        self, local_id, camera_id, timestamp_ms,
        floor_x, floor_y, zone_id,
        bbox_confidence, bbox_area,
        bbox_x1, bbox_y1, bbox_x2, bbox_y2,
    ) -> None:
        self._pos_buffer.append(dict(
            local_id=str(local_id), timestamp_ms=timestamp_ms,
            floor_x=floor_x, floor_y=floor_y, zone_id=str(zone_id) if zone_id else None,
            bbox_confidence=bbox_confidence, bbox_area=bbox_area,
            bbox_x1=bbox_x1, bbox_y1=bbox_y1, bbox_x2=bbox_x2, bbox_y2=bbox_y2,
        ))

    def flush_temp_positions(self, local_id: uuid.UUID, camera_id: str, positions: list) -> None:
        for p in positions:
            self._pos_buffer.append(dict(
                local_id=str(local_id), timestamp_ms=p.timestamp_ms,
                floor_x=p.floor_x, floor_y=p.floor_y,
                zone_id=str(p.zone_id) if getattr(p, "zone_id", None) else None,
                bbox_confidence=getattr(p, "bbox_confidence", 0.0),
                bbox_area=getattr(p, "bbox_area", 0.0),
                bbox_x1=getattr(p, "bbox_x1", 0.0), bbox_y1=getattr(p, "bbox_y1", 0.0),
                bbox_x2=getattr(p, "bbox_x2", 0.0), bbox_y2=getattr(p, "bbox_y2", 0.0),
            ))

    async def write_embedding(
        self, local_id: uuid.UUID, camera_id: str, captured_ts: int,
        embedding: np.ndarray, yolo_confidence: float, is_init: bool,
    ) -> None:
        self._emb_buffer.append(dict(
            local_id=str(local_id), captured_ts=captured_ts,
            embedding=embedding.tolist(),
            yolo_confidence=yolo_confidence, is_init=is_init,
        ))

    async def upsert_centroid(
        self, local_id: uuid.UUID, camera_id: str,
        centroid: np.ndarray, batch_number: int,
    ) -> None:
        self._cen_buffer.append(dict(
            local_id=str(local_id),
            centroid=centroid.tolist(),
            batch_number=batch_number,
        ))

    def maybe_flush(self, camera_id: str, force: bool = False) -> None:
        # Sync entry point — runtime calls this; actual flush is async.
        # We just mark that a flush is needed; flush_async() is called by runtime.
        pass

    async def flush_async(
        self, camera_id: str, batch_number: int,
        window_start_ms: int, window_end_ms: int,
    ) -> None:
        """Send accumulated batch to EEP. Called at every batch boundary."""
        if not self._pos_buffer and not self._emb_buffer and not self._cen_buffer:
            return

        payload = {
            "camera_id": camera_id,
            "batch_number": batch_number,
            "window_start_ms": window_start_ms,
            "window_end_ms": window_end_ms,
            "positions": self._pos_buffer,
            "embeddings": self._emb_buffer,
            "centroids": self._cen_buffer,
        }
        self._pos_buffer = []
        self._emb_buffer = []
        self._cen_buffer = []

        url = (
            f"{self._s.EEP_BASE_URL.rstrip('/')}"
            f"/internal/stores/{self._store_id}/tracking-batch"
        )
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                url,
                json=payload,
                headers={"X-Internal-Token": self._s.VISION_INTERNAL_TOKEN},
            )
            resp.raise_for_status()
