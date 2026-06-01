"""Annotated-video rendering for the demo.

A second pass over each camera's video that draws the reconciled **Global ID**
and the per-camera **Local ID** onto the real IEP2 detection bounding boxes.
Boxes come from ``tracking_history`` so rendering reads Marji's persisted
production results instead of re-running detection.
"""

from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

from sqlalchemy import text

from common.db.engine import session_scope


async def _load_overlays(camera_id: str) -> list[dict]:
    """Return persisted detection boxes plus local/global IDs sorted by time."""
    async with session_scope() as session:
        rows = await session.execute(
            text(
                """
                SELECT th.timestamp_ms, th.local_id::text AS local_id,
                       th.bbox_x1, th.bbox_y1, th.bbox_x2, th.bbox_y2,
                       th.bbox_confidence,
                       COALESCE(glm.global_id::text, 'unmapped') AS global_id
                FROM tracking_history th
                LEFT JOIN LATERAL (
                    SELECT global_id
                    FROM global_local_mapping
                    WHERE local_id = th.local_id
                    ORDER BY linked_at_batch DESC
                    LIMIT 1
                ) glm ON TRUE
                WHERE th.camera_id = :cam
                ORDER BY th.timestamp_ms
                """
            ),
            {"cam": camera_id},
        )
        return [dict(r._mapping) for r in rows]


def _draw_label(cv2, frame, x: int, y: int, text_value: str, color: tuple[int, int, int]) -> None:
    font = cv2.FONT_HERSHEY_SIMPLEX
    scale = 0.62
    thickness = 2
    (tw, th), baseline = cv2.getTextSize(text_value, font, scale, thickness)
    y0 = max(0, y - th - baseline - 8)
    cv2.rectangle(frame, (x, y0), (min(frame.shape[1] - 1, x + tw + 8), y0 + th + baseline + 8), color, -1)
    cv2.putText(frame, text_value, (x + 4, y0 + th + 3), font, scale, (255, 255, 255), thickness, cv2.LINE_AA)


def _reencode_for_browser(path: Path) -> Path:
    """Convert OpenCV's MP4 output to browser-safe H.264 when ffmpeg exists."""
    if path.suffix.lower() != ".mp4" or shutil.which("ffmpeg") is None:
        return path
    tmp = path.with_name(f"{path.stem}.browser{path.suffix}")
    result = subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(path),
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            "-an",
            str(tmp),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if result.returncode != 0 or not tmp.exists():
        tmp.unlink(missing_ok=True)
        return path
    tmp.replace(path)
    return path


async def render_camera(video_path: str, camera_id: str, output_path: str,
                        start_ms: int, sample_fps: float) -> str:
    """Re-read the video, overlay each persisted detection's IDs and bbox,
    write an annotated video. Returns the output path."""
    import cv2

    from tools.demo.colors import global_id_bgr

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
        for item in overlays:
            if abs(item["timestamp_ms"] - ts) > tol_ms:
                continue
            if None in (item["bbox_x1"], item["bbox_y1"], item["bbox_x2"], item["bbox_y2"]):
                continue
            gid = item["global_id"]
            lid = item["local_id"]
            color = global_id_bgr(gid)
            x1 = max(0, min(w - 1, int(round(item["bbox_x1"]))))
            y1 = max(0, min(h - 1, int(round(item["bbox_y1"]))))
            x2 = max(0, min(w - 1, int(round(item["bbox_x2"]))))
            y2 = max(0, min(h - 1, int(round(item["bbox_y2"]))))
            if x2 <= x1 or y2 <= y1:
                continue
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 3)
            conf = item["bbox_confidence"]
            label = f"Global {gid[:8]} | Local {lid[:8]}"
            if conf is not None:
                label += f" | {float(conf):.2f}"
            _draw_label(cv2, frame, x1, y1, label, color)
        writer.write(frame)
        idx += 1

    cap.release()
    writer.release()
    out = _reencode_for_browser(out)
    return str(out)
