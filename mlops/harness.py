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
_VIEW_MAX_W = 1280   # downscale saved frames to this width — full scene, ~200KB, views in any viewer


def _annotate(frame: np.ndarray, dets: list) -> np.ndarray:
    """Draw person boxes on a copy of the frame, then downscale to a viewer-friendly
    width. Big source frames (e.g. 3072x2048, ~6MB PNG) get clipped by image
    previewers; downscaling keeps the WHOLE scene + all boxes in a small image.
    Box thickness/font scale with resolution so they stay visible after downscale."""
    img = frame.copy()
    h, w = img.shape[:2]
    thick = max(2, round(w / 600))
    fs = max(0.5, w / 1500)
    for x1, y1, x2, y2, p, _ in dets:
        cv2.rectangle(img, (int(x1), int(y1)), (int(x2), int(y2)), (0, 0, 255), thick)
        cv2.putText(img, f"person {p:.2f}", (int(x1), max(0, int(y1) - 5)),
                    cv2.FONT_HERSHEY_SIMPLEX, fs, (0, 0, 255), thick)
    if w > _VIEW_MAX_W:
        scale = _VIEW_MAX_W / w
        img = cv2.resize(img, (_VIEW_MAX_W, int(h * scale)), interpolation=cv2.INTER_AREA)
    return img


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
    sample_frames: list = field(default_factory=list)   # (frame_idx, annotated BGR image)
    peak_frame: tuple = None                            # (frame_idx, count, annotated image) — busiest frame
    _peak_count: int = -1                               # internal tracker for peak_frame
    # ── Tracking-experiment bookkeeping (confirmed tracks, not raw detections) ──
    per_frame_track_counts: list = field(default_factory=list)  # confirmed tracks alive per frame
    track_frames: dict = field(default_factory=dict)            # track_id -> sorted list of frames it was seen
    tracker_time_s: float = 0.0                                 # time spent ONLY in tracker.update()


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
        # boxmot 10.0.83 class is BYTETracker; uses track_thresh (not new_track_thresh).
        from boxmot import BYTETracker
        return BYTETracker(track_thresh=0.6, match_thresh=match_thresh,
                           track_buffer=15, frame_rate=5)
    if name == "ocsort":
        # boxmot 10.0.83 class is OCSORT; motion-only, no match_thresh / no appearance.
        from boxmot import OCSORT
        return OCSORT()
    if name == "strongsort":
        # StrongSORT uses an appearance model (needs real reid weights) — that is the
        # point of testing it. boxmot downloads osnet_x0_25_msmt17 on first use.
        from boxmot import StrongSORT
        return StrongSORT(model_weights=Path("osnet_x0_25_msmt17.pt"),
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

        # Save an annotated sample frame (boxes drawn, downscaled for viewing).
        if frame_idx in sample_idxs:
            stats.sample_frames.append((frame_idx, _annotate(frame, dets)))

        # Track the PEAK frame — the single frame with the most detections — so the
        # busiest moment (which the evenly-spaced samples may miss) is always saved.
        if len(dets) > stats._peak_count:
            stats._peak_count = len(dets)
            stats.peak_frame = (frame_idx, len(dets), _annotate(frame, dets))

        # Tracker for identity-based stats. Time ONLY the tracker.update() call so
        # per_frame_assoc_ms / throughput_fps reflect the tracker, not detection.
        dets_arr = np.array(dets, dtype=float) if dets else np.empty((0, 6))
        _tt = time.monotonic()
        tracks = tracker.update(dets_arr, frame)
        stats.tracker_time_s += time.monotonic() - _tt

        current_ids = {int(t[4]) for t in tracks} if len(tracks) else set()
        stats.track_ids_seen |= current_ids

        # Confirmed tracks alive this frame (for peak_confirmed_tracks).
        stats.per_frame_track_counts.append(len(current_ids))
        # Record every frame each track id is actually seen (for a HONEST
        # avg_track_lifetime = frames-present, not first..last span; and for the
        # track-timeline Gantt artifact).
        for tid in current_ids:
            stats.track_frames.setdefault(tid, []).append(frame_idx)

        # crude id-switch proxy: ids that vanished then a brand-new id appeared same frame
        vanished = last_track_ids - current_ids
        appeared = current_ids - last_track_ids
        if vanished and appeared:
            stats.id_switches += min(len(vanished), len(appeared))
        last_track_ids = current_ids

    cap.release()
    stats.elapsed_s = time.monotonic() - t0
    return stats


# ══════════════════════════════════════════════════════════════════════════════
# ReID experiment harness
# ══════════════════════════════════════════════════════════════════════════════
# Fixes detection (rtdetr-x conf0.5) + tracker (botsort), varies the ReID model +
# threshold. Implements a lightweight lost-pool recovery (mirrors the concept of
# services/iep2_vision/identity/LocalIdentityManager): a disappeared track goes to a
# lost pool with its embedding gallery + TTL; a NEW tracker ID checks the pool by
# cosine similarity >= threshold to recover a prior local_id or mint a new one.
# All metrics are PROXIES (no identity ground truth) — see metrics/reid_metrics.py.

_REID_TTL_FRAMES = 150     # 30 s at 5 fps, matches LocalIdentityManager TTL_FRAMES
_REID_SAMPLE_EVERY = 5     # embed a track's crop every N frames (gallery building)


@dataclass
class ReidStats:
    frames_processed: int = 0
    unique_local_ids: int = 0
    reid_attempts: int = 0       # new tracker IDs that checked the lost pool
    reid_recoveries: int = 0     # of those, how many re-matched a lost identity
    embedding_dim: int = 0
    avg_embed_ms: float = 0.0
    total_runtime_s: float = 0.0          # wall-clock for the whole run
    sum_recovery_sim: float = 0.0         # accumulates cosine of accepted recoveries
    attempt_sims: list = field(default_factory=list)   # cosine at EVERY recovery attempt (for histogram)
    recovery_pairs: list = field(default_factory=list)  # [(gallery_crop, new_crop, sim)] sample (for montage)
    _embed_time_s: float = 0.0
    _embed_calls: int = 0


_REID_ARCHS = {"osnet_x1_0", "osnet_x0_75", "osnet_x0_5", "osnet_x0_25",
               "osnet_ibn_x1_0", "osnet_ain_x1_0", "resnet50", "mlfn"}


class _ImageNetReidBackend:
    """Wraps a raw torchreid arch (ImageNet-pretrained, NOT ReID-trained) so it has
    the same get_features(xyxys, frame) interface as boxmot's backend. Used for the
    bare-name baseline (e.g. osnet_x1_0) which has no ReID-trained weights in boxmot's
    registry — exactly the 'wrong weights' control from reid_experiments.md."""
    def __init__(self, model, device):
        import torch
        self._m = model.eval().to(device)
        self._device = device
        self._torch = torch

    def get_features(self, xyxys, frame):
        import numpy as np, cv2
        t = self._torch
        feats = []
        for x1, y1, x2, y2 in xyxys[:, :4].astype(int):
            crop = frame[max(0, y1):max(1, y2), max(0, x1):max(1, x2)]
            if crop.size == 0:
                feats.append(np.zeros(512, dtype=np.float32)); continue
            crop = cv2.resize(crop, (128, 256))                      # torchreid input WxH
            crop = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
            mean = np.array([0.485, 0.456, 0.406]); std = np.array([0.229, 0.224, 0.225])
            crop = (crop - mean) / std
            tens = t.from_numpy(crop.transpose(2, 0, 1)[None]).float().to(self._device)
            with t.no_grad():
                v = self._m(tens).cpu().numpy()[0].astype(np.float32)
            feats.append(v)
        return np.array(feats, dtype=np.float32)


def _load_reid_backend(weights: str):
    """Return an object with get_features(xyxys, frame) -> (N, dim) embeddings.

    Two paths:
      * dataset-trained weights (e.g. osnet_x1_0_msmt17.pt, resnet50_msmt17.pt) →
        boxmot ReidAutoBackend (same as services/reid_service/service_dev.py).
      * bare architecture name (e.g. osnet_x1_0) → build the arch with ImageNet
        pretrained backbone (torchreid pretrained=True), wrapped to match the API.
        boxmot has no ReID-trained URL for bare names — this is the untrained baseline.
    """
    from pathlib import Path
    import torch
    device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
    stem = weights[:-3] if weights.endswith(".pt") else weights
    if stem in _REID_ARCHS:   # bare arch → ImageNet baseline
        from boxmot.appearance.reid_model_factory import build_model
        model = build_model(stem, num_classes=1, pretrained=True, use_gpu=torch.cuda.is_available())
        return _ImageNetReidBackend(model, device)
    from boxmot.appearance.reid_auto_backend import ReidAutoBackend
    rab = ReidAutoBackend(weights=Path(weights), device=device, half=False)
    return rab.model  # has .get_features(xyxys, frame) -> (N, dim) L2-normalised


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    na = np.linalg.norm(a); nb = np.linalg.norm(b)
    if na < 1e-8 or nb < 1e-8:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


def run_reid_clip(
    reid_weights: str,
    video_path: str,
    reid_threshold: float = 0.75,
    det_weights: str = "rtdetr-x.pt",
    conf: float = 0.5,
    imgsz: int = 640,
    seed: int = 42,
) -> ReidStats:
    """Detection+tracking FIXED; embed crops with `reid_weights`; recover identities
    via lost-pool cosine matching at `reid_threshold`. Returns proxy ReidStats."""
    np.random.seed(seed)
    try:
        import torch
        torch.manual_seed(seed)
    except Exception:
        pass

    model = _load_detector(det_weights)
    tracker = _load_tracker("botsort", 0.8)
    reid = _load_reid_backend(reid_weights)
    device = _resolve_device()

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise FileNotFoundError(f"Cannot open video: {video_path}")

    stats = ReidStats()
    _t_start = time.monotonic()
    next_local_id = 1
    track_to_local: dict = {}                 # tracker_id -> local_id (active binding)
    galleries: dict = {}                      # local_id -> list[np.ndarray] (embeddings)
    last_crop: dict = {}                      # local_id -> most recent BGR crop (for montage)
    lost_pool: dict = {}                      # local_id -> {"gallery":[...], "lost_at":frame, "crop":img}
    last_track_ids: set = set()
    frame_idx = -1

    def _embed(xyxy, frame):
        t = time.monotonic()
        feats = reid.get_features(np.array([xyxy], dtype=float), frame)
        stats._embed_time_s += time.monotonic() - t
        stats._embed_calls += 1
        v = np.asarray(feats[0], dtype=np.float32)
        if stats.embedding_dim == 0:
            stats.embedding_dim = v.shape[0]
        return v

    while True:
        ok, frame = cap.read()
        if not ok:
            break
        frame_idx += 1
        stats.frames_processed += 1

        results = model(frame, conf=conf, imgsz=imgsz, device=device, verbose=False)[0]
        dets = []
        if results.boxes is not None and len(results.boxes) > 0:
            cls = results.boxes.cls.cpu().numpy().astype(int)
            cf = results.boxes.conf.cpu().numpy()
            xyxy = results.boxes.xyxy.cpu().numpy()
            for c, p, box in zip(cls, cf, xyxy):
                if c == PERSON_CLASS_ID:
                    dets.append([float(box[0]), float(box[1]), float(box[2]), float(box[3]), float(p), 0.0])

        dets_arr = np.array(dets, dtype=float) if dets else np.empty((0, 6))
        tracks = tracker.update(dets_arr, frame)

        # Expire lost-pool entries past TTL.
        for lid in [l for l, e in lost_pool.items() if frame_idx - e["lost_at"] > _REID_TTL_FRAMES]:
            del lost_pool[lid]

        def _crop(box):
            x1, y1, x2, y2 = [int(v) for v in box]
            c = frame[max(0, y1):max(1, y2), max(0, x1):max(1, x2)]
            return c if c.size else None

        current_ids = set()
        for row in tracks:
            tid = int(row[4]); xyxy = [float(row[0]), float(row[1]), float(row[2]), float(row[3])]
            current_ids.add(tid)

            if tid in track_to_local:
                lid = track_to_local[tid]
            else:
                # New tracker ID → try to recover from the lost pool (a ReID attempt).
                stats.reid_attempts += 1
                emb = _embed(xyxy, frame)
                best_lid, best_sim = None, -1.0
                for cand_lid, entry in lost_pool.items():
                    sim = max(_cosine(emb, g) for g in entry["gallery"]) if entry["gallery"] else 0.0
                    if sim > best_sim:
                        best_sim, best_lid = sim, cand_lid
                if best_lid is not None:
                    stats.attempt_sims.append(best_sim)   # for similarity histogram
                if best_lid is not None and best_sim >= reid_threshold:
                    lid = best_lid                      # recovered
                    entry = lost_pool.pop(lid)
                    galleries[lid] = entry["gallery"]; galleries[lid].append(emb)
                    stats.reid_recoveries += 1
                    stats.sum_recovery_sim += best_sim
                    # Montage: keep a sample of (gallery crop, recovered crop, sim).
                    new_crop = _crop(xyxy)
                    if len(stats.recovery_pairs) < 8 and entry.get("crop") is not None and new_crop is not None:
                        stats.recovery_pairs.append((entry["crop"], new_crop, best_sim))
                else:
                    lid = next_local_id; next_local_id += 1   # mint new identity
                    galleries[lid] = [emb]
                track_to_local[tid] = lid

            _c = _crop(xyxy)
            if _c is not None:
                last_crop[lid] = _c
            # Periodically grow the gallery for active tracks.
            if frame_idx % _REID_SAMPLE_EVERY == 0:
                galleries.setdefault(lid, []).append(_embed(xyxy, frame))

        # Tracks that disappeared this frame → push their local_id to the lost pool.
        for tid in (last_track_ids - current_ids):
            lid = track_to_local.pop(tid, None)
            if lid is not None and lid in galleries:
                lost_pool[lid] = {"gallery": galleries[lid][-10:], "lost_at": frame_idx,
                                  "crop": last_crop.get(lid)}
        last_track_ids = current_ids

    cap.release()
    stats.unique_local_ids = next_local_id - 1
    stats.avg_embed_ms = (stats._embed_time_s / stats._embed_calls * 1000.0) if stats._embed_calls else 0.0
    stats.total_runtime_s = time.monotonic() - _t_start
    return stats
