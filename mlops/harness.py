"""Shared offline evaluation harness (Path A: standalone Ultralytics/boxmot).

Loads detectors/trackers DIRECTLY (not through the IEP2 ZMQ services) so the eval
scripts can freely swap models for comparison/tuning sweeps — exactly how the
docs/docs_models experiments were produced. CPU-friendly; needs no running services.

Gap 1: every clip is processed to COMPLETION (all frames), never stopped on a timer,
so `frames_processed` is identical across runs and metrics are comparable.

Person class id = 0 (COCO). Detection is filtered to persons only, matching the
production R4 rule in services/yolo_service.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

import cv2
import numpy as np

PERSON_CLASS_ID = 0


def _resolve_device() -> str:
    """Pick the inference device. Honors INFERENCE_DEVICE env (cpu|gpu|cuda|auto)
    but falls back to cpu if CUDA isn't actually available. Returns an ultralytics-
    style device string: '0' for the first GPU, or 'cpu'."""
    import os
    requested = os.environ.get("INFERENCE_DEVICE", "auto").lower()
    try:
        import torch
        cuda_ok = torch.cuda.is_available()
    except Exception:
        cuda_ok = False
    if requested == "cpu":
        return "cpu"
    if requested in ("gpu", "cuda", "auto"):
        return "0" if cuda_ok else "cpu"
    return "cpu"


# ── Per-run accumulated raw stats (metrics derived from these) ──────────────────

@dataclass
class FrameStats:
    frames_processed: int = 0
    total_detections: int = 0          # every person detection across all frames
    confidences: list[float] = field(default_factory=list)
    bbox_areas: list[float] = field(default_factory=list)
    per_frame_counts: list[int] = field(default_factory=list)   # detections per frame
    track_ids_seen: set = field(default_factory=set)            # distinct tracker IDs
    id_switches: int = 0
    elapsed_s: float = 0.0
    sample_frames: list = field(default_factory=list)  # (frame_idx, annotated BGR image)


def _load_detector(weights: str):
    """Load an Ultralytics detector; RT-DETR vs YOLO chosen by filename, mirroring
    services/yolo_service/service_dev.py `_load_model`."""
    name = weights.lower()
    if name.startswith("rtdetr"):
        from ultralytics import RTDETR as _Model
    else:
        from ultralytics import YOLO as _Model
    return _Model(weights)


def _load_tracker(tracker_name: str, match_thresh: float = 0.8):
    """Load a boxmot tracker (boxmot 10.0.8x). The BoT-SORT call mirrors the
    project's own services/iep2_vision/tracker/tracker.py exactly: motion-only
    (with_reid=False), so `model_weights` is an empty Path and never read."""
    from pathlib import Path
    import torch
    name = tracker_name.lower()
    device = torch.device("cpu")

    if name == "botsort":
        from boxmot import BoTSORT
        return BoTSORT(
            model_weights=Path(""),          # unused: with_reid=False
            device=device,
            fp16=False,
            track_buffer=15,
            match_thresh=match_thresh,
            new_track_thresh=0.7,
            track_high_thresh=0.6,
            cmc_method="sof",
            frame_rate=5,
            with_reid=False,
        )
    if name == "bytetrack":
        from boxmot import ByteTrack
        return ByteTrack(track_buffer=15, match_thresh=match_thresh, frame_rate=5)
    if name == "ocsort":
        from boxmot import OcSort
        return OcSort()
    if name == "strongsort":
        from boxmot import StrongSort
        return StrongSort(model_weights=Path("osnet_x0_25_msmt17.pt"),
                          device=device, fp16=False)
    raise ValueError(f"Unknown tracker: {tracker_name}")


def run_detection_clip(
    weights: str,
    video_path: str,
    conf: float = 0.3,
    imgsz: int = 640,
    tracker_name: str = "botsort",
    match_thresh: float = 0.8,
    seed: int = 42,
) -> FrameStats:
    """Run detector (+ tracker for identity stats) over EVERY frame of the clip.

    Returns raw FrameStats; the eval script converts these into MLflow metrics.
    Processes to completion — no wall-clock cutoff (Gap 1).
    """
    np.random.seed(seed)
    try:
        import torch
        torch.manual_seed(seed)
    except Exception:
        pass

    model = _load_detector(weights)
    tracker = _load_tracker(tracker_name, match_thresh)  # motion-only → CPU is fine
    device = _resolve_device()  # '0' (GPU) or 'cpu' for the detector
    import logging
    logging.getLogger("mlops.harness").info("Detector device: %s", device)

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise FileNotFoundError(f"Cannot open video: {video_path}")

    # Pick frame indices to save as annotated samples (evenly spaced through the clip).
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
    n_samples = 5
    sample_idxs = (
        {int(total * i / (n_samples + 1)) for i in range(1, n_samples + 1)}
        if total > n_samples else set()
    )

    stats = FrameStats()
    last_track_ids: set = set()
    frame_idx = -1
    t0 = time.monotonic()

    while True:
        ok, frame = cap.read()
        if not ok:
            break  # end of file — processed to completion
        frame_idx += 1
        stats.frames_processed += 1

        results = model(frame, conf=conf, imgsz=imgsz, device=device, verbose=False)[0]

        dets = []  # [x1,y1,x2,y2,conf,cls] for persons only
        if results.boxes is not None and len(results.boxes) > 0:
            cls = results.boxes.cls.cpu().numpy().astype(int)
            cf = results.boxes.conf.cpu().numpy()
            xyxy = results.boxes.xyxy.cpu().numpy()
            for c, p, box in zip(cls, cf, xyxy):
                if c != PERSON_CLASS_ID:
                    continue
                x1, y1, x2, y2 = [float(v) for v in box]
                dets.append([x1, y1, x2, y2, float(p), 0.0])
                stats.total_detections += 1
                stats.confidences.append(float(p))
                stats.bbox_areas.append((x2 - x1) * (y2 - y1))

        stats.per_frame_counts.append(len(dets))

        # Save an annotated sample frame (boxes drawn) for visual FP evidence.
        if frame_idx in sample_idxs:
            annotated = frame.copy()
            for x1, y1, x2, y2, p, _ in dets:
                cv2.rectangle(annotated, (int(x1), int(y1)), (int(x2), int(y2)), (0, 0, 255), 2)
                cv2.putText(annotated, f"person {p:.2f}", (int(x1), max(0, int(y1) - 5)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)
            stats.sample_frames.append((frame_idx, annotated))

        # Tracker for identity-based stats (unique IDs, id switches).
        dets_arr = np.array(dets, dtype=float) if dets else np.empty((0, 6))
        tracks = tracker.update(dets_arr, frame)
        current_ids = {int(t[4]) for t in tracks} if len(tracks) else set()
        stats.track_ids_seen |= current_ids
        # crude id-switch proxy: ids that vanished then a brand-new id appeared same frame
        vanished = last_track_ids - current_ids
        appeared = current_ids - last_track_ids
        if vanished and appeared:
            stats.id_switches += min(len(vanished), len(appeared))
        last_track_ids = current_ids

    cap.release()
    stats.elapsed_s = time.monotonic() - t0
    return stats
