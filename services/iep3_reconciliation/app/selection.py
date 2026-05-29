"""Process 2 -- position selection (IEP3 spec §5).

For each active Global ID, pick the single best camera's position this window by
a weighted score, write exactly one canonical ``global_tracking_history`` row,
and update the GlobalID's last known position.
"""

from __future__ import annotations

from sqlalchemy import text


def selection_score(bbox_area, confidence, frame_pixels, w_area, w_conf) -> float:
    normalized_area = bbox_area / frame_pixels if frame_pixels else 0.0
    return w_area * normalized_area + w_conf * confidence


class PositionSelector:
    def __init__(self, repo, settings, frame_pixels_by_camera: dict[str, int]):
        self._repo, self._s = repo, settings
        self._frame_px = frame_pixels_by_camera

    async def write_canonical_positions(
        self, session, store_id, batch, window_start, window_end
    ) -> int:
        rows = await session.execute(
            text(
                """
                SELECT glm.global_id, th.camera_id, th.local_id,
                       th.floor_x, th.floor_y, th.zone_id, th.timestamp_ms,
                       th.bbox_confidence, th.bbox_area
                FROM tracking_history th
                JOIN global_local_mapping glm ON th.local_id = glm.local_id
                WHERE glm.is_active = TRUE
                  AND th.timestamp_ms >= :start AND th.timestamp_ms < :end
                """
            ),
            {"start": window_start, "end": window_end},
        )

        best: dict = {}  # global_id -> (score, row)
        for r in rows:
            score = selection_score(
                r.bbox_area or 0,
                r.bbox_confidence or 0,
                self._frame_px.get(r.camera_id, 1),
                self._s.selection_weight_bbox_area,
                self._s.selection_weight_confidence,
            )
            cur = best.get(r.global_id)
            if cur is None or score > cur[0]:
                best[r.global_id] = (score, r)

        for gid, (score, r) in best.items():
            await self._repo.write_global_position(
                session,
                global_id=gid,
                store_id=store_id,
                batch_number=batch,
                timestamp_ms=r.timestamp_ms,
                floor_x=r.floor_x,
                floor_y=r.floor_y,
                zone_id=r.zone_id,
                source_camera=r.camera_id,
                source_local_id=r.local_id,
                selection_score=score,
            )
            await self._repo.update_global_last_position(session, gid, r.floor_x, r.floor_y, r.timestamp_ms)
        return len(best)
