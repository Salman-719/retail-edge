"""Annotated-video rendering for the demo.

A second pass over each camera's video that draws the reconciled **Global ID**
(not the per-camera Local ID) onto frames, so the demo visually proves
cross-camera identity consistency. Global IDs are resolved by joining
``global_local_mapping``; floor positions come from ``tracking_history`` and are
projected back to pixels via the inverse homography (no pixel bbox is stored and
detection is not re-run -- a clean, schema-preserving demo path).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from sqlalchemy import text

from common.db.engine import session_scope


async def _load_homography(camera_id: str) -> np.ndarray:
    async with session_scope() as session:
        flat = (
            await session.execute(
                text("SELECT homography FROM camera_calibrations WHERE cam_id = :c"),
                {"c": camera_id},
            )
        ).scalar_one()
    return np.array(flat, dtype=np.float64).reshape(3, 3)


async def _load_overlays(camera_id: str) -> list[tuple[int, float, float, str]]:
    """Returns (timestamp_ms, floor_x, floor_y, global_id-or-'unmapped') sorted by time."""
    async with session_scope() as session:
        rows = await session.execute(
            text(
                """
                SELECT th.timestamp_ms, th.floor_x, th.floor_y,
                       COALESCE(glm.global_id::text, 'unmapped') AS global_id
                FROM tracking_history th
                LEFT JOIN global_local_mapping glm
                  ON th.local_id = glm.local_id AND glm.is_active = TRUE
                WHERE th.camera_id = :cam
                ORDER BY th.timestamp_ms
                """
            ),
            {"cam": camera_id},
        )
        return [(r.timestamp_ms, r.floor_x, r.floor_y, r.global_id) for r in rows]


def _floor_to_pixel(h_inv: np.ndarray, fx: float, fy: float) -> tuple[int, int] | None:
    p = h_inv @ np.array([fx, fy, 1.0])
    if abs(p[2]) < 1e-9:
        return None
    return int(p[0] / p[2]), int(p[1] / p[2])


async def render_camera(video_path: str, camera_id: str, output_path: str,
                        start_ms: int, sample_fps: float) -> str:
    """Re-read the video, overlay each detection's GlobalID at its floor pixel,
    write an annotated video. Returns the output path."""
    import cv2

    from tools.demo.colors import global_id_bgr

    h_inv = np.linalg.inv(await _load_homography(camera_id))
    overlays = await _load_overlays(camera_id)

    cap = cv2.VideoCapture(video_path)
    src_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or 640
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 480
    tol_ms = (1000.0 / sample_fps) / 2.0

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(str(out), cv2.VideoWriter_fourcc(*"mp4v"), src_fps, (w, h))
    if not writer.isOpened():  # fallback codec
        out = out.with_suffix(".avi")
        writer = cv2.VideoWriter(str(out), cv2.VideoWriter_fourcc(*"MJPG"), src_fps, (w, h))

    idx = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        ts = start_ms + int((idx / src_fps) * 1000)
        for o_ts, fx, fy, gid in overlays:
            if abs(o_ts - ts) <= tol_ms:
                px = _floor_to_pixel(h_inv, fx, fy)
                if px is None:
                    continue
                color = global_id_bgr(gid)
                cv2.circle(frame, px, 10, color, -1)
                cv2.putText(frame, gid[:8], (px[0] + 12, px[1]), cv2.FONT_HERSHEY_SIMPLEX,
                            0.6, color, 2, cv2.LINE_AA)
        writer.write(frame)
        idx += 1

    cap.release()
    writer.release()
    return str(out)
