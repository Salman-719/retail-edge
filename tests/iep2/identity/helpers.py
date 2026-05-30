"""Shared test doubles for the identity layer (no DB, no real models)."""

from __future__ import annotations

import numpy as np

from common.contracts.geometry import BBox
from services.iep2_vision.app.vision.pipeline import FrameDetection
from services.iep2_vision.app.vision.tracker import TrackerOutput


class FakePersistence:
    """Records every PersistencePort call for assertions. The DB-touching
    methods are async to match the real M4 contract."""

    def __init__(self) -> None:
        self.positions: list[dict] = []
        self.flushed: list[dict] = []
        self.embeddings: list[dict] = []
        self.centroids: list[dict] = []

    def append_position(self, local_id, camera_id, timestamp_ms, floor_x, floor_y,
                        zone_id, bbox_confidence, bbox_area) -> None:
        self.positions.append(dict(local_id=local_id, camera_id=camera_id, timestamp_ms=timestamp_ms,
                                   floor_x=floor_x, floor_y=floor_y, zone_id=zone_id,
                                   bbox_confidence=bbox_confidence, bbox_area=bbox_area))

    def flush_temp_positions(self, local_id, camera_id, positions) -> None:
        self.flushed.append(dict(local_id=local_id, camera_id=camera_id, count=len(positions)))

    async def write_embedding(self, local_id, camera_id, captured_ts, embedding,
                              yolo_confidence, is_init) -> None:
        self.embeddings.append(dict(local_id=local_id, camera_id=camera_id, captured_ts=captured_ts,
                                    is_init=is_init))

    async def upsert_centroid(self, local_id, camera_id, centroid, batch_number) -> None:
        self.centroids.append(dict(local_id=local_id, camera_id=camera_id, batch_number=batch_number))

    async def maybe_flush(self, force: bool = False) -> None:
        # No buffering in the fake; positions are recorded eagerly in append_position.
        self.flush_calls = getattr(self, "flush_calls", 0) + 1


class LabelEmbedder:
    """Deterministic embedder keyed by a crop's mean pixel value: identical crop
    content -> identical embedding (cosine 1.0); different content -> orthogonal.
    Lets tests control ReID matches precisely without real models."""

    embedding_dim = 512

    def extract(self, crop: np.ndarray) -> np.ndarray:
        vec = np.zeros(self.embedding_dim, dtype=np.float32)
        if crop is None or crop.size == 0:
            return vec
        idx = int(round(float(crop.mean()))) % self.embedding_dim
        vec[idx] = 1.0
        return vec


def make_frame(label: int, size: tuple[int, int] = (480, 640)) -> np.ndarray:
    """A frame filled with a constant value so any crop has mean == label."""
    return np.full((size[0], size[1], 3), label, dtype=np.uint8)


def person_det(track_id: int, x: float, y: float, *, conf: float = 0.9,
               zone: str | None = "A") -> FrameDetection:
    """A processed detection with a valid floor position (foot point ~ (x, y))."""
    from common.contracts.geometry import FloorPosition

    bbox = BBox(x, y - 200, x + 80, y)  # tall person box; area = 80 * 200 = 16000
    return FrameDetection(track_id=track_id, bbox=bbox, confidence=conf,
                          floor_pos=FloorPosition(x + 40, y), zone_id=zone)


def tracker(new=None, confirmed=None, lost=None) -> TrackerOutput:
    return TrackerOutput(confirmed=confirmed or [], new=new or [], lost_track_ids=lost or [])


def as_tracked(dets):
    """FrameDetection -> a minimal object exposing .track_id for TrackerOutput."""
    from common.contracts.detection import TrackedDetection

    return [TrackedDetection(track_id=d.track_id, bbox=d.bbox, confidence=d.confidence) for d in dets]
