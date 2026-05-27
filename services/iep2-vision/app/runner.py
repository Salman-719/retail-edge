from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from html import escape
import math
from pathlib import Path
import subprocess
from typing import Any, Callable

from app.reid import AppearanceEmbedder, IdentityGallery
from app.schemas import Test1RunRequest
from app.storage import RUNTIME_DIR, SERVICE_ROOT, find_test1_dir, run_dir, write_json
from app.vision import create_people_tracker


StatusCallback = Callable[[dict[str, Any]], None]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_crop(frame: Any, bbox: list[float]) -> Any:
    height, width = frame.shape[:2]
    x1, y1, x2, y2 = [int(round(v)) for v in bbox]
    x1 = max(0, min(width - 1, x1))
    y1 = max(0, min(height - 1, y1))
    x2 = max(0, min(width, x2))
    y2 = max(0, min(height, y2))
    if x2 <= x1 or y2 <= y1:
        return frame[0:0, 0:0]
    return frame[y1:y2, x1:x2]


def _bbox_area(bbox: list[float]) -> float:
    return max(0.0, float(bbox[2]) - float(bbox[0])) * max(0.0, float(bbox[3]) - float(bbox[1]))


def _intersection_area(left: list[float], right: list[float]) -> float:
    x1 = max(float(left[0]), float(right[0]))
    y1 = max(float(left[1]), float(right[1]))
    x2 = min(float(left[2]), float(right[2]))
    y2 = min(float(left[3]), float(right[3]))
    return max(0.0, x2 - x1) * max(0.0, y2 - y1)


def _iou(left: list[float], right: list[float]) -> float:
    intersection = _intersection_area(left, right)
    if intersection <= 0:
        return 0.0
    union = _bbox_area(left) + _bbox_area(right) - intersection
    if union <= 0:
        return 0.0
    return intersection / union


def _suppress_duplicate_detections(
    detections: list[Any],
    iou_threshold: float,
    containment_threshold: float,
) -> tuple[list[Any], int]:
    ranked = sorted(
        detections,
        key=lambda detection: (_bbox_area(detection.bbox), detection.confidence),
        reverse=True,
    )
    kept: list[Any] = []
    suppressed = 0

    for detection in ranked:
        area = _bbox_area(detection.bbox)
        duplicate = False
        for kept_detection in kept:
            kept_area = _bbox_area(kept_detection.bbox)
            intersection = _intersection_area(detection.bbox, kept_detection.bbox)
            containment = 0.0 if area <= 0 else intersection / area
            is_nested_partial = containment >= containment_threshold and area <= kept_area * 0.85
            if _iou(detection.bbox, kept_detection.bbox) >= iou_threshold or is_nested_partial:
                duplicate = True
                break

        if duplicate:
            suppressed += 1
        else:
            kept.append(detection)

    return sorted(kept, key=lambda detection: detection.local_track_id), suppressed


def _filter_low_quality_person_boxes(
    detections: list[Any],
    frame_shape: tuple[int, ...],
    min_height_ratio: float,
    min_aspect_ratio: float,
) -> tuple[list[Any], int]:
    frame_height = max(1, int(frame_shape[0]))
    kept = []
    filtered = 0

    for detection in detections:
        x1, y1, x2, y2 = detection.bbox
        width = max(0.0, float(x2) - float(x1))
        height = max(0.0, float(y2) - float(y1))
        height_ratio = height / frame_height
        aspect_ratio = height / max(width, 1.0)
        if height_ratio < min_height_ratio or aspect_ratio < min_aspect_ratio:
            filtered += 1
            continue
        kept.append(detection)

    return kept, filtered


def _identity_color(global_person_id: str) -> tuple[int, int, int]:
    palette = [
        (38, 132, 255),
        (42, 201, 122),
        (255, 159, 28),
        (222, 82, 255),
        (64, 224, 208),
        (255, 99, 132),
        (180, 180, 40),
        (120, 170, 255),
    ]
    digits = "".join(ch for ch in global_person_id if ch.isdigit())
    index = int(digits or "1") - 1
    return palette[index % len(palette)]


def _short_match_type(match_type: str) -> str:
    return {
        "existing_local_track": "same track",
        "cross_camera_reid": "cross camera",
        "local_id_switch_recovered": "id recovered",
        "new_identity": "new id",
    }.get(match_type, match_type.replace("_", " "))


def _draw_text_panel(
    frame: Any,
    lines: list[str],
    origin: tuple[int, int],
    color: tuple[int, int, int],
    scale: float = 0.72,
    thickness: int = 2,
) -> tuple[int, int, int, int]:
    import cv2

    x, y = origin
    font = cv2.FONT_HERSHEY_SIMPLEX
    padding_x = 8
    padding_y = 7
    line_gap = 6
    sizes = [cv2.getTextSize(line, font, scale, thickness)[0] for line in lines]
    text_w = max((size[0] for size in sizes), default=0)
    text_h = max((size[1] for size in sizes), default=0)
    panel_w = text_w + padding_x * 2
    panel_h = len(lines) * text_h + max(0, len(lines) - 1) * line_gap + padding_y * 2

    height, width = frame.shape[:2]
    x = max(0, min(x, max(0, width - panel_w - 1)))
    y = max(panel_h + 1, min(y, height - 2))
    top_left = (x, y - panel_h)
    bottom_right = (x + panel_w, y)
    cv2.rectangle(frame, top_left, bottom_right, (0, 0, 0), -1)
    cv2.rectangle(frame, top_left, bottom_right, color, 2)

    cursor_y = y - panel_h + padding_y + text_h
    for line in lines:
        cv2.putText(
            frame,
            line,
            (x + padding_x, cursor_y),
            font,
            scale,
            (255, 255, 255),
            thickness,
            cv2.LINE_AA,
        )
        cursor_y += text_h + line_gap
    return (top_left[0], top_left[1], bottom_right[0], bottom_right[1])


def _panel_size(lines: list[str], scale: float, thickness: int) -> tuple[int, int]:
    import cv2

    font = cv2.FONT_HERSHEY_SIMPLEX
    padding_x = 8
    padding_y = 7
    line_gap = 6
    sizes = [cv2.getTextSize(line, font, scale, thickness)[0] for line in lines]
    text_w = max((size[0] for size in sizes), default=0)
    text_h = max((size[1] for size in sizes), default=0)
    return (
        text_w + padding_x * 2,
        len(lines) * text_h + max(0, len(lines) - 1) * line_gap + padding_y * 2,
    )


def _rect_overlaps(left: tuple[int, int, int, int], right: tuple[int, int, int, int], padding: int = 4) -> bool:
    return not (
        left[2] + padding < right[0]
        or right[2] + padding < left[0]
        or left[3] + padding < right[1]
        or right[3] + padding < left[1]
    )


def _label_origin(
    frame: Any,
    bbox: list[float],
    panel_size: tuple[int, int],
    occupied_rects: list[tuple[int, int, int, int]],
) -> tuple[int, int]:
    height, width = frame.shape[:2]
    x1, y1, x2, y2 = [int(round(v)) for v in bbox]
    panel_w, panel_h = panel_size
    candidates = [
        (x1, y1 - 8),
        (x1, y2 + panel_h + 8),
        (x2 + 8, y1 + panel_h),
        (x1 - panel_w - 8, y1 + panel_h),
        (x2 - panel_w, y2 + panel_h + 8),
    ]

    for raw_x, raw_y in candidates:
        x = max(0, min(raw_x, max(0, width - panel_w - 1)))
        y = max(panel_h + 1, min(raw_y, height - 2))
        rect = (x, y - panel_h, x + panel_w, y)
        if not any(_rect_overlaps(rect, occupied) for occupied in occupied_rects):
            return (x, y)

    return (max(0, min(x1, max(0, width - panel_w - 1))), max(panel_h + 1, min(y2 + panel_h + 8, height - 2)))


def _draw_observations(
    frame: Any,
    observations: list[dict[str, Any]],
    camera_id: str,
    frame_index: int,
    timestamp_sec: float,
) -> Any:
    import cv2

    annotated = frame.copy()
    header = [f"{camera_id}  frame {frame_index}  {timestamp_sec:.2f}s  detections {len(observations)}"]
    occupied_rects = [_draw_text_panel(annotated, header, (12, 36), (255, 255, 255), scale=0.78, thickness=2)]

    for observation in observations:
        x1, y1, x2, y2 = [int(round(v)) for v in observation["bbox"]]
        color = _identity_color(observation["global_person_id"])
        label_lines = [
            f'{observation["global_person_id"]}   T{observation["local_track_id"]}',
            f'{observation["confidence"]:.2f}   {_short_match_type(observation["identity_match_type"])}',
        ]
        cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 4)
        label_scale = 0.68
        label_thickness = 2
        origin = _label_origin(
            annotated,
            observation["bbox"],
            _panel_size(label_lines, scale=label_scale, thickness=label_thickness),
            occupied_rects,
        )
        occupied_rects.append(
            _draw_text_panel(
                annotated,
                label_lines,
                origin,
                color,
                scale=label_scale,
                thickness=label_thickness,
            )
        )
    return annotated


def _create_video_writer(cv2: Any, base_path: Path, fps: float, size: tuple[int, int]) -> tuple[Any, Path, str]:
    candidates = [
        (base_path.with_name(f"{base_path.name}_raw").with_suffix(".avi"), "MJPG"),
        (base_path.with_name(f"{base_path.name}_raw").with_suffix(".mp4"), "mp4v"),
    ]

    for path, codec in candidates:
        writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*codec), max(1.0, fps), size)
        if writer.isOpened():
            return writer, path, codec
        writer.release()
        path.unlink(missing_ok=True)

    raise RuntimeError(f"Unable to create annotated video writer for {base_path}")


def _encode_browser_video(raw_path: Path, output_path: Path) -> tuple[Path, str]:
    command = [
        "ffmpeg",
        "-y",
        "-loglevel",
        "error",
        "-i",
        str(raw_path),
        "-an",
        "-vcodec",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "23",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        str(output_path),
    ]
    try:
        subprocess.run(command, check=True, capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise RuntimeError("ffmpeg is required to create browser-playable annotated MP4 videos.") from exc
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr.strip() or exc.stdout.strip() or str(exc)
        raise RuntimeError(f"ffmpeg failed while encoding {output_path}: {detail}") from exc

    raw_path.unlink(missing_ok=True)
    return output_path, "h264"


def _write_review_page(output_dir: Path, result: dict[str, Any], annotated_videos: list[dict[str, Any]]) -> str:
    cards = []
    mode_label = "Every source frame" if result["process_every_frame"] else "Sampled full source duration"
    limit_label = "No frame cap" if result["max_frames_per_camera"] is None else f'{result["max_frames_per_camera"]} frames/camera cap'
    for video in annotated_videos:
        rel = Path(video["path"]).relative_to(output_dir)
        cards.append(
            f"""
            <section class="video-card">
              <h2>{escape(video["camera_id"])}</h2>
              <video controls preload="metadata" playsinline muted src="{escape(rel.as_posix())}"></video>
              <p>{escape(video["codec"])} · {video["frames"]} frames · {video["fps"]} fps · {video["width"]}x{video["height"]}</p>
            </section>
            """
        )

    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>IEP2 Run {escape(result["run_id"])}</title>
  <style>
    body {{ margin: 0; font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #111; color: #f5f5f5; }}
    main {{ max-width: 1180px; margin: 0 auto; padding: 24px; }}
    h1 {{ font-size: 22px; margin: 0 0 8px; }}
    h2 {{ font-size: 16px; margin: 0 0 8px; }}
    p {{ color: #cfcfcf; margin: 6px 0 0; }}
    a {{ color: #8ec5ff; }}
    button {{ background: #f5f5f5; border: 0; color: #111; cursor: pointer; font-weight: 700; padding: 10px 14px; }}
    video {{ width: 100%; aspect-ratio: 16 / 9; object-fit: contain; background: #000; border: 1px solid #333; }}
    .meta {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 8px; margin: 16px 0; }}
    .meta div {{ background: #1c1c1c; border: 1px solid #333; padding: 10px; }}
    .sync-controls {{ align-items: center; display: flex; flex-wrap: wrap; gap: 10px; margin: 16px 0; }}
    .sync-controls span {{ color: #cfcfcf; }}
    .video-grid {{ display: grid; gap: 14px; grid-template-columns: repeat(auto-fit, minmax(360px, 1fr)); }}
    .video-card {{ background: #171717; border: 1px solid #333; padding: 12px; }}
  </style>
</head>
<body>
  <main>
    <h1>IEP2 Tracking + ReID Review</h1>
    <p>Run {escape(result["run_id"])} · tracker {escape(result["tracker"])} · detector {escape(result["detector_model"])}</p>
    <div class="meta">
      <div>Identities<br><strong>{result["identity_count"]}</strong></div>
      <div>Tracks<br><strong>{result["track_count"]}</strong></div>
      <div>Observations<br><strong>{result["observation_count"]}</strong></div>
      <div>Low-quality boxes removed<br><strong>{result["filtered_low_quality_detections"]}</strong></div>
      <div>Duplicate boxes removed<br><strong>{result["suppressed_duplicate_detections"]}</strong></div>
      <div>Mode<br><strong>{escape(mode_label)}</strong></div>
      <div>Limit<br><strong>{escape(limit_label)}</strong></div>
      <div>Timeline<br><strong>{result["timeline_frames"]} frames · {result["timeline_fps"]} fps</strong></div>
      <div>Gallery<br><strong>{result["identity_gallery_size"]} embeddings/id</strong></div>
    </div>
    <div class="sync-controls">
      <button id="play-sync" type="button">Play synced</button>
      <button id="pause-sync" type="button">Pause</button>
      <button id="reset-sync" type="button">Reset</button>
      <span id="sync-status">Synced timeline</span>
    </div>
    <div class="video-grid">{"".join(cards)}</div>
    <p><a href="results.json">results.json</a> · <a href="tracks.json">tracks.json</a> · <a href="identities.json">identities.json</a> · <a href="identity_gallery.json">identity_gallery.json</a></p>
  </main>
  <script>
    const videos = Array.from(document.querySelectorAll("video"));
    const statusNode = document.getElementById("sync-status");
    let syncing = false;

    function alignTo(master) {{
      for (const video of videos) {{
        if (video === master) continue;
        if (Math.abs(video.currentTime - master.currentTime) > 0.08) {{
          video.currentTime = master.currentTime;
        }}
      }}
    }}

    async function playSynced(master = videos[0]) {{
      if (!master) return;
      syncing = true;
      alignTo(master);
      await Promise.allSettled(videos.map((video) => video.play()));
      syncing = false;
      statusNode.textContent = `Synced at ${{master.currentTime.toFixed(2)}}s`;
    }}

    function pauseSynced(master = videos[0]) {{
      if (!master) return;
      syncing = true;
      alignTo(master);
      videos.forEach((video) => video.pause());
      syncing = false;
      statusNode.textContent = `Paused at ${{master.currentTime.toFixed(2)}}s`;
    }}

    function resetSynced() {{
      syncing = true;
      videos.forEach((video) => {{
        video.pause();
        video.currentTime = 0;
      }});
      syncing = false;
      statusNode.textContent = "Synced timeline";
    }}

    for (const video of videos) {{
      video.addEventListener("play", () => {{
        if (!syncing) playSynced(video);
      }});
      video.addEventListener("pause", () => {{
        if (!syncing && !videos.every((item) => item.paused)) pauseSynced(video);
      }});
      video.addEventListener("seeking", () => {{
        if (!syncing) {{
          syncing = true;
          alignTo(video);
          syncing = false;
        }}
      }});
      video.addEventListener("timeupdate", () => {{
        if (!syncing) alignTo(video);
      }});
    }}

    document.getElementById("play-sync").addEventListener("click", () => playSynced());
    document.getElementById("pause-sync").addEventListener("click", () => pauseSynced());
    document.getElementById("reset-sync").addEventListener("click", resetSynced);
  </script>
</body>
</html>
"""
    review_path = output_dir / "review.html"
    review_path.write_text(html, encoding="utf-8")
    return str(review_path)


def execute_test1_run(run_id: str, request: Test1RunRequest, update_status: StatusCallback) -> None:
    try:
        import cv2
    except Exception as exc:  # pragma: no cover - dependency availability is environment-specific
        raise RuntimeError(
            "opencv-python-headless is required. Install services/iep2-vision/requirements.txt."
        ) from exc

    output_dir = run_dir(run_id)
    annotated_root = output_dir / "annotated"
    annotated_root.mkdir(parents=True, exist_ok=True)

    test1_dir = find_test1_dir(request.test1_dir)
    video_paths = {
        "camera1": test1_dir / "Camera1.mp4",
        "camera2": test1_dir / "Camera2.mp4",
    }

    raw_video_metadata: dict[str, dict[str, Any]] = {}
    for camera_id, video_path in video_paths.items():
        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            raise RuntimeError(f"Unable to open video for {camera_id}: {video_path}")
        source_fps = float(cap.get(cv2.CAP_PROP_FPS) or 30.0)
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        cap.release()

        raw_video_metadata[camera_id] = {
            "source_fps": source_fps,
            "frame_count": frame_count,
            "width": width,
            "height": height,
        }

    timeline_fps = (
        max(metadata["source_fps"] for metadata in raw_video_metadata.values())
        if request.process_every_frame
        else request.sample_rate_fps
    )
    video_metadata: dict[str, dict[str, Any]] = {}
    available_values: list[int] = []
    for camera_id, metadata in raw_video_metadata.items():
        source_fps = float(metadata["source_fps"])
        frame_count = int(metadata["frame_count"])
        if frame_count > 0 and source_fps > 0:
            source_duration_sec = max(0.0, (frame_count - 1) / source_fps)
            available_frames = int(math.floor(source_duration_sec * timeline_fps)) + 1
            available_values.append(available_frames)
        else:
            source_duration_sec = 0.0
            available_frames = request.max_frames_per_camera

        video_metadata[camera_id] = {
            **metadata,
            "source_duration_sec": source_duration_sec,
            "sample_interval": 1 if request.process_every_frame else max(1, int(round(source_fps / timeline_fps))),
            "output_fps": timeline_fps,
            "available_frames": available_frames,
            "target_frames": available_frames,
        }

    shared_target_frames = min(available_values) if len(available_values) == len(video_metadata) else request.max_frames_per_camera
    if request.max_frames_per_camera is not None:
        shared_target_frames = (
            request.max_frames_per_camera
            if shared_target_frames is None
            else min(shared_target_frames, request.max_frames_per_camera)
        )
    for metadata in video_metadata.values():
        metadata["target_frames"] = shared_target_frames

    expected_frames = None if shared_target_frames is None else shared_target_frames * len(video_metadata)

    update_status({
        "status": "running",
        "progress": 0.01,
        "artifact_dir": str(output_dir),
        "cameras": list(video_paths.keys()),
        "frames_expected": expected_frames,
    })

    tracker_config = Path(request.tracker_config) if request.tracker_config else SERVICE_ROOT / "botsort_reid.yaml"
    model_dir = RUNTIME_DIR / "models"
    default_reid_weights = model_dir / "osnet_x1_0_msmt17.pt"
    reid_weights = request.reid_weights or str(default_reid_weights)

    embedder = AppearanceEmbedder(
        backend=request.reid_backend,
        model_name=request.reid_model,
        model_path=reid_weights,
        device=request.device,
    )
    gallery = IdentityGallery(
        threshold=request.match_threshold,
        min_cross_camera_observations=request.min_cross_camera_observations,
        gallery_size=request.identity_gallery_size,
    )

    observations: list[dict[str, Any]] = []
    tracks: dict[str, dict[str, Any]] = {}
    camera_summaries: dict[str, dict[str, Any]] = {}
    annotated_files: list[str] = []
    annotated_videos: list[dict[str, Any]] = []
    identity_match_counts = {
        "new_identity": 0,
        "existing_local_track": 0,
        "cross_camera_reid": 0,
        "local_id_switch_recovered": 0,
        "identity_merged": 0,
    }
    suppressed_duplicate_detections = 0
    filtered_low_quality_detections = 0

    processed_frames = 0
    if shared_target_frames is None:
        raise RuntimeError("Unable to determine synchronized frame count. Set max_frames_per_camera.")

    camera_states: dict[str, dict[str, Any]] = {}
    for camera_id, input_video_path in video_paths.items():
        camera_dir = annotated_root / camera_id
        camera_dir.mkdir(parents=True, exist_ok=True)

        cap = cv2.VideoCapture(str(input_video_path))
        if not cap.isOpened():
            raise RuntimeError(f"Unable to open video for {camera_id}: {input_video_path}")

        metadata = video_metadata[camera_id]
        source_fps = float(metadata["source_fps"])
        frame_count = int(metadata["frame_count"])
        width = int(metadata["width"])
        height = int(metadata["height"])
        sample_interval = int(metadata["sample_interval"])
        output_fps = float(metadata["output_fps"])
        tracker = create_people_tracker(
            detector_backend=request.detector_backend,
            tracker_backend=request.tracker_backend,
            detector_model=request.detector_model,
            detector_weights=request.detector_weights,
            confidence_threshold=request.confidence_threshold,
            nms_threshold=request.nms_threshold,
            yolox_input_size=(request.yolox_input_height, request.yolox_input_width),
            tracker_config=tracker_config,
            reid_weights=reid_weights,
            device=request.device,
        )

        camera_states[camera_id] = {
            "input_video_path": input_video_path,
            "camera_dir": camera_dir,
            "cap": cap,
            "tracker": tracker,
            "source_fps": source_fps,
            "frame_count": frame_count,
            "width": width,
            "height": height,
            "sample_interval": sample_interval,
            "output_fps": output_fps,
            "sampled_for_camera": 0,
            "camera_observation_count": 0,
            "camera_suppressed_duplicate_detections": 0,
            "camera_filtered_low_quality_detections": 0,
            "track_observation_counts": defaultdict(int),
        }

    try:
        for sample_index in range(shared_target_frames):
            timestamp_sec = sample_index / timeline_fps if timeline_fps > 0 else float(sample_index)
            tick_items: list[dict[str, Any]] = []

            for camera_id, state in camera_states.items():
                cap = state["cap"]
                source_fps = float(state["source_fps"])
                frame_count = int(state["frame_count"])
                frame_index = min(
                    max(0, frame_count - 1),
                    int(round(timestamp_sec * source_fps)) if source_fps > 0 else sample_index,
                )
                cap.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
                ok, frame = cap.read()
                if not ok:
                    raise RuntimeError(f"Unable to read synchronized frame {frame_index} for {camera_id}.")

                tracker = state["tracker"]
                tracked = tracker.track_people(frame)
                tracked, filtered_count = _filter_low_quality_person_boxes(
                    tracked,
                    frame_shape=frame.shape,
                    min_height_ratio=request.min_detection_height_ratio,
                    min_aspect_ratio=request.min_detection_aspect_ratio,
                )
                tracked, suppressed_count = _suppress_duplicate_detections(
                    tracked,
                    iou_threshold=request.duplicate_iou_threshold,
                    containment_threshold=request.duplicate_containment_threshold,
                )
                filtered_low_quality_detections += filtered_count
                state["camera_filtered_low_quality_detections"] += filtered_count
                suppressed_duplicate_detections += suppressed_count
                state["camera_suppressed_duplicate_detections"] += suppressed_count
                tick_detections: list[dict[str, Any]] = []

                for detection in tracked:
                    crop = _safe_crop(frame, detection.bbox)
                    embedding = embedder.embed(crop)
                    tick_detections.append({
                        "detection": detection,
                        "embedding": embedding,
                    })

                state["sampled_for_camera"] += 1
                processed_frames += 1
                tick_items.append({
                    "camera_id": camera_id,
                    "state": state,
                    "frame_index": frame_index,
                    "timestamp_sec": timestamp_sec,
                    "detections": tick_detections,
                })

            for item in tick_items:
                camera_id = item["camera_id"]
                state = item["state"]
                frame_index = item["frame_index"]
                timestamp_sec = item["timestamp_sec"]

                for detection_item in item["detections"]:
                    detection = detection_item["detection"]
                    local_track_id = detection.local_track_id
                    embedding = detection_item["embedding"]
                    assignment = gallery.assign(
                        camera_id=camera_id,
                        local_track_id=local_track_id,
                        embedding=embedding,
                        timestamp_sec=timestamp_sec,
                    )
                    global_id = assignment.global_person_id
                    distance = assignment.match_distance
                    if assignment.merged_global_person_id is not None:
                        identity_match_counts["identity_merged"] += 1
                        for previous_observation in observations:
                            if previous_observation["global_person_id"] == assignment.merged_global_person_id:
                                previous_observation["global_person_id"] = global_id
                        for previous_track in tracks.values():
                            if previous_track["global_person_id"] == assignment.merged_global_person_id:
                                previous_track["global_person_id"] = global_id
                    identity_match_counts[assignment.match_type] = (
                        identity_match_counts.get(assignment.match_type, 0) + 1
                    )
                    observation = {
                        "camera_id": camera_id,
                        "timeline_index": sample_index,
                        "timeline_timestamp_sec": round(timestamp_sec, 3),
                        "frame_index": frame_index,
                        "timestamp_sec": round(timestamp_sec, 3),
                        "local_track_id": local_track_id,
                        "global_person_id": global_id,
                        "bbox": [round(float(v), 2) for v in detection.bbox],
                        "confidence": round(float(detection.confidence), 4),
                        "match_distance": None if distance is None else round(float(distance), 4),
                        "match_similarity": None if distance is None else round(float(1.0 - distance), 4),
                        "matched_existing_identity": assignment.matched_existing_identity,
                        "identity_match_type": assignment.match_type,
                        "merged_global_person_id": assignment.merged_global_person_id,
                    }
                    observations.append(observation)
                    state["camera_observation_count"] += 1
                    state["track_observation_counts"][local_track_id] += 1

                    track_key = f"{camera_id}:{local_track_id}"
                    if track_key not in tracks:
                        tracks[track_key] = {
                            "camera_id": camera_id,
                            "local_track_id": local_track_id,
                            "global_person_id": global_id,
                            "first_identity_match_type": assignment.match_type,
                            "first_seen_sec": round(timestamp_sec, 3),
                            "last_seen_sec": round(timestamp_sec, 3),
                            "observations": 0,
                        }
                    tracks[track_key]["global_person_id"] = global_id
                    tracks[track_key]["last_seen_sec"] = round(timestamp_sec, 3)
                    tracks[track_key]["observations"] += 1

            if sample_index == 0 or (sample_index + 1) % 10 == 0:
                progress = min(0.98, processed_frames / max(expected_frames or 1, 1))
                update_status({
                    "status": "running",
                    "progress": round(progress, 4),
                    "frames_processed": processed_frames,
                    "frames_expected": expected_frames,
                    "observations": len(observations),
                    "identities": len(gallery.to_json()),
                })
    finally:
        for state in camera_states.values():
            state["cap"].release()

    observations_by_timeline: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for observation in observations:
        observations_by_timeline[(observation["camera_id"], int(observation["timeline_index"]))].append(observation)

    for camera_id, state in camera_states.items():
        cap = cv2.VideoCapture(str(state["input_video_path"]))
        if not cap.isOpened():
            raise RuntimeError(f"Unable to reopen video for rendering {camera_id}: {state['input_video_path']}")

        video_writer, raw_video_path, raw_video_codec = _create_video_writer(
            cv2=cv2,
            base_path=annotated_root / camera_id,
            fps=float(state["output_fps"]),
            size=(int(state["width"]), int(state["height"])),
        )
        try:
            for sample_index in range(int(state["sampled_for_camera"])):
                timestamp_sec = sample_index / timeline_fps if timeline_fps > 0 else float(sample_index)
                source_fps = float(state["source_fps"])
                frame_count = int(state["frame_count"])
                frame_index = min(
                    max(0, frame_count - 1),
                    int(round(timestamp_sec * source_fps)) if source_fps > 0 else sample_index,
                )
                cap.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
                ok, frame = cap.read()
                if not ok:
                    raise RuntimeError(f"Unable to render synchronized frame {frame_index} for {camera_id}.")

                frame_observations = observations_by_timeline.get((camera_id, sample_index), [])
                annotated = _draw_observations(
                    frame=frame,
                    observations=frame_observations,
                    camera_id=camera_id,
                    frame_index=frame_index,
                    timestamp_sec=timestamp_sec,
                )
                video_writer.write(annotated)

                if (sample_index + 1) % request.annotated_stride == 0:
                    artifact_path = state["camera_dir"] / f"frame_{frame_index:06d}.jpg"
                    cv2.imwrite(str(artifact_path), annotated)
                    annotated_files.append(str(artifact_path))
        finally:
            cap.release()
            video_writer.release()

        annotated_video_path, video_codec = _encode_browser_video(
            raw_path=raw_video_path,
            output_path=annotated_root / f"{camera_id}.mp4",
        )
        annotated_video = {
            "camera_id": camera_id,
            "path": str(annotated_video_path),
            "codec": video_codec,
            "source_codec": raw_video_codec,
            "fps": round(float(state["output_fps"]), 3),
            "frames": state["sampled_for_camera"],
            "width": state["width"],
            "height": state["height"],
        }
        annotated_videos.append(annotated_video)
        track_observation_counts = state["track_observation_counts"]
        camera_summaries[camera_id] = {
            "video_path": str(state["input_video_path"]),
            "source_fps": round(float(state["source_fps"]), 3),
            "source_frames": state["frame_count"],
            "width": state["width"],
            "height": state["height"],
            "sample_interval": state["sample_interval"],
            "output_fps": round(float(state["output_fps"]), 3),
            "sampled_frames": state["sampled_for_camera"],
            "observations": state["camera_observation_count"],
            "tracks": len(track_observation_counts),
            "filtered_low_quality_detections": state["camera_filtered_low_quality_detections"],
            "suppressed_duplicate_detections": state["camera_suppressed_duplicate_detections"],
            "annotated_video": str(annotated_video_path),
        }

    update_status({
        "status": "running",
        "progress": 0.99,
        "frames_processed": processed_frames,
        "frames_expected": expected_frames,
        "observations": len(observations),
        "identities": len(gallery.to_json()),
    })

    identities = gallery.to_json()
    identity_gallery = gallery.gallery_to_json(include_vectors=True)
    track_list = sorted(tracks.values(), key=lambda row: (row["camera_id"], row["local_track_id"]))
    result = {
        "run_id": run_id,
        "status": "complete",
        "created_at": _utc_now(),
        "test1_dir": str(test1_dir),
        "detector_backend": request.detector_backend,
        "detector_model": request.detector_model,
        "detector_weights": request.detector_weights,
        "tracker": request.tracker_backend,
        "tracker_config": str(tracker_config),
        "reid_backend": request.reid_backend,
        "reid_model": request.reid_model,
        "reid_weights": reid_weights,
        "confidence_threshold": request.confidence_threshold,
        "nms_threshold": request.nms_threshold,
        "yolox_input_size": [request.yolox_input_height, request.yolox_input_width],
        "duplicate_iou_threshold": request.duplicate_iou_threshold,
        "duplicate_containment_threshold": request.duplicate_containment_threshold,
        "min_detection_height_ratio": request.min_detection_height_ratio,
        "min_detection_aspect_ratio": request.min_detection_aspect_ratio,
        "min_cross_camera_observations": request.min_cross_camera_observations,
        "identity_gallery_size": request.identity_gallery_size,
        "identity_gallery_policy": "Store up to 6 diverse normalized embeddings per global identity by default; match uses minimum cosine distance to any saved embedding.",
        "sample_rate_fps": request.sample_rate_fps,
        "process_every_frame": request.process_every_frame,
        "max_frames_per_camera": request.max_frames_per_camera,
        "match_threshold": request.match_threshold,
        "match_metric": "cosine_distance",
        "match_rule": "same identity when min gallery distance <= match_threshold",
        "synchronized_processing": True,
        "processing_mode": "timestamp_batch_two_phase",
        "render_after_final_identity_resolution": True,
        "timeline_fps": round(timeline_fps, 3),
        "timeline_frames": shared_target_frames,
        "timeline_duration_sec": round(shared_target_frames / timeline_fps, 3) if timeline_fps > 0 else None,
        "embedding_backend": embedder.backend,
        "filtered_low_quality_detections": filtered_low_quality_detections,
        "suppressed_duplicate_detections": suppressed_duplicate_detections,
        "identity_match_counts": identity_match_counts,
        "cameras": camera_summaries,
        "identity_count": len(identities),
        "track_count": len(track_list),
        "observation_count": len(observations),
        "annotated_files": annotated_files,
        "annotated_videos": annotated_videos,
        "identities": identities,
        "identity_gallery": identity_gallery,
        "tracks": track_list,
        "observations": observations,
    }
    result["review_page"] = _write_review_page(output_dir, result, annotated_videos)

    write_json(output_dir / "identities.json", identities)
    write_json(output_dir / "identity_gallery.json", identity_gallery)
    write_json(output_dir / "tracks.json", track_list)
    write_json(output_dir / "results.json", result)

    update_status({
        "status": "complete",
        "progress": 1.0,
        "frames_processed": processed_frames,
        "frames_expected": expected_frames,
        "observations": len(observations),
        "identities": len(identities),
        "artifact_dir": str(output_dir),
    })
