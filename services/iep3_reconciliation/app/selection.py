"""PositionSelector — Process 2: select best camera source per GlobalID
and write one canonical global_tracking_history row per batch.
"""
from __future__ import annotations

import logging
import uuid
from collections import defaultdict

import asyncpg

from app.repository import Iep3Repository, PositionRow, CameraBatchInfo
from app.settings import Iep3Settings

logger = logging.getLogger(__name__)


def _selection_score(
    bbox_area: float,
    bbox_confidence: float,
    frame_width: int,
    frame_height: int,
    weight_area: float,
    weight_confidence: float,
) -> float:
    """Weighted score for a camera report.

    normalized_area ∈ [0, 1] — fraction of frame occupied by bbox, clamped.
    bbox_confidence ∈ [0, 1] — YOLO detection confidence.
    """
    frame_px = frame_width * frame_height
    if frame_px <= 0:
        return weight_confidence * bbox_confidence
    normalized_area = min(bbox_area / frame_px, 1.0)
    return weight_area * normalized_area + weight_confidence * bbox_confidence


class PositionSelector:

    def __init__(
        self,
        repo: Iep3Repository,
        settings: Iep3Settings,
    ) -> None:
        self._repo = repo
        self._settings = settings
        # Resolution cache: (camera_id, camera_config_id) → (width, height)
        # Invalidates naturally on version activation — camera_config_id changes,
        # old entry is never accessed again (new key → cache miss).
        self._resolution_cache: dict[tuple[str, str], tuple[int, int]] = {}

    async def write_canonical_positions(
        self,
        conn: asyncpg.Connection,
        store_id: str,
        batch_number: int,
        window_start_ms: int,
        window_end_ms: int,
    ) -> int:
        """Write one global_tracking_history row per active GlobalID.

        Returns count of rows written.
        """
        # 1. Fetch all position rows for active GlobalIDs in this window (one query)
        positions = await self._repo.get_positions_for_selection(
            conn, store_id, window_start_ms, window_end_ms
        )
        if not positions:
            logger.debug(
                "PositionSelector: no positions for store=%s window=[%d,%d]",
                store_id, window_start_ms, window_end_ms,
            )
            return 0

        # 2. Resolve camera batch info (camera_config_id, version_id) in bulk
        # Standalone call — acquires own connection, outside the batch transaction
        unique_cameras = list({p.camera_id for p in positions})
        batch_info_map = await self._repo.get_camera_batch_info_bulk(unique_cameras)

        # 3. Resolve resolutions with (camera_id, camera_config_id) cache
        resolution_map = await self._resolve_resolutions(
            unique_cameras, batch_info_map
        )

        # 4. Group positions by global_id in Python
        by_global: dict[uuid.UUID, list[PositionRow]] = defaultdict(list)
        for pos in positions:
            by_global[pos.global_id].append(pos)

        # 5. Score, select winner, write one row per GlobalID
        written = 0
        for global_id, reports in by_global.items():
            winner, score = self._select_best(reports, resolution_map)
            if winner is None:
                continue

            info = batch_info_map.get(winner.camera_id)
            version_id = info.version_id if info else None

            await self._repo.write_global_position(
                conn=conn,
                global_id=global_id,
                store_id=store_id,
                version_id=version_id,
                batch_number=batch_number,
                timestamp_ms=winner.timestamp_ms,
                floor_x=winner.floor_x,
                floor_y=winner.floor_y,
                zone_id=winner.zone_id,
                source_camera=winner.camera_id,
                source_local_id=winner.local_id,
                selection_score=float(score),
            )

            await self._repo.update_global_last_seen(
                conn=conn,
                global_id=global_id,
                floor_x=winner.floor_x,
                floor_y=winner.floor_y,
                last_seen_ts=winner.timestamp_ms,
                zone_id=winner.zone_id,
                set_entry_zone=winner.needs_entry_zone,
            )

            written += 1

        logger.info(
            "PositionSelector: wrote %d canonical positions for batch=%d",
            written, batch_number,
        )
        return written

    def _select_best(
        self,
        reports: list[PositionRow],
        resolution_map: dict[str, tuple[int, int]],
    ) -> tuple[PositionRow | None, float]:
        """Score all reports for one GlobalID and return (winner, score).

        Returns (None, 0.0) if reports is empty.
        """
        best_pos: PositionRow | None = None
        best_score: float = -1.0

        for report in reports:
            w, h = resolution_map.get(
                report.camera_id,
                (self._settings.default_frame_width,
                 self._settings.default_frame_height),
            )
            score = _selection_score(
                bbox_area=report.bbox_area,
                bbox_confidence=report.bbox_confidence,
                frame_width=w,
                frame_height=h,
                weight_area=self._settings.selection_weight_area,
                weight_confidence=self._settings.selection_weight_confidence,
            )
            if score > best_score:
                best_score = score
                best_pos = report

        return best_pos, best_score

    async def _resolve_resolutions(
        self,
        camera_ids: list[str],
        batch_info_map: dict[str, CameraBatchInfo],
    ) -> dict[str, tuple[int, int]]:
        """Return {camera_id: (width, height)} for all cameras.

        Cache key: (camera_id, camera_config_id). On version activation,
        camera_config_id changes → natural cache miss → fresh DB query.
        Falls back to env var defaults if all DB sources are NULL.
        """
        result: dict[str, tuple[int, int]] = {}

        for camera_id in camera_ids:
            info = batch_info_map.get(camera_id)
            if info is None:
                logger.warning(
                    "No open camera_runtime_session for camera=%s "
                    "— using default resolution %dx%d",
                    camera_id,
                    self._settings.default_frame_width,
                    self._settings.default_frame_height,
                )
                result[camera_id] = (
                    self._settings.default_frame_width,
                    self._settings.default_frame_height,
                )
                continue

            cache_key = (camera_id, info.camera_config_id)

            if cache_key in self._resolution_cache:
                result[camera_id] = self._resolution_cache[cache_key]
                continue

            # Cache miss — query full resolution fallback chain
            res = await self._repo.get_camera_resolution(camera_id)
            if res is not None:
                dims = (res.width, res.height)
            else:
                dims = (
                    self._settings.default_frame_width,
                    self._settings.default_frame_height,
                )
                logger.warning(
                    "No resolution found for camera=%s — using default %dx%d",
                    camera_id,
                    self._settings.default_frame_width,
                    self._settings.default_frame_height,
                )

            # Cache under this config_id (default also cached to avoid re-querying)
            self._resolution_cache[cache_key] = dims
            result[camera_id] = dims
            logger.debug(
                "Resolution cached: camera=%s config=%s — %dx%d",
                camera_id, info.camera_config_id, dims[0], dims[1],
            )

        return result
