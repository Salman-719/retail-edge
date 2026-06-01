"""In-memory identity pools for one camera (IEP2 spec §11).

The three pools (Active, Pending, Lost) are plain dicts wrapped in a small class
for lifecycle clarity. Pruning happens ONLY via ``prune_lost``, which the manager
calls exactly once per batch boundary -- the deterministic, fixed-point cleanup
the spec mandates (M3 review issues B4/19). Nothing prunes per-frame.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

import numpy as np

from services.iep2_vision.app.identity.gallery import EmbeddingGallery


@dataclass
class TempPosition:
    timestamp_ms: int
    floor_x: float
    floor_y: float
    zone_id: str | None
    bbox_confidence: float
    bbox_area: float
    bbox_x1: float
    bbox_y1: float
    bbox_x2: float
    bbox_y2: float


@dataclass
class ActiveTrack:
    track_id: int
    local_id: uuid.UUID
    camera_id: str
    floor_x: float
    floor_y: float
    zone_id: str | None
    last_seen_ts: int
    bbox_confidence: float
    confirmed_frames: int
    sample_counter: int
    gallery: EmbeddingGallery


@dataclass
class PendingTrack:
    track_id: int
    camera_id: str
    created_ts: int
    embeddings: list[np.ndarray] = field(default_factory=list)  # grows to init count, no gate
    embedding_ts: list[int] = field(default_factory=list)  # captured_ts parallel to embeddings
    temp_positions: list[TempPosition] = field(default_factory=list)
    last_floor_x: float | None = None
    last_floor_y: float | None = None
    last_seen_ts: int | None = None


@dataclass
class LostEntry:
    local_id: uuid.UUID
    camera_id: str
    last_floor_x: float
    last_floor_y: float
    last_seen_ts: int
    expiry_batch: int
    centroid: np.ndarray
    gallery: list[np.ndarray]


class IdentityPools:
    """Owns the three pools for one camera. Keyed as in the spec."""

    def __init__(self) -> None:
        self.active: dict[int, ActiveTrack] = {}  # by track_id
        self.pending: dict[int, PendingTrack] = {}  # by track_id
        self.lost: dict[uuid.UUID, LostEntry] = {}  # by local_id

    def prune_lost(self, current_batch: int) -> list[uuid.UUID]:
        """Remove expired lost entries. Called at batch boundary ONLY. Returns
        the local_ids pruned (for logging/metrics)."""
        expired = [lid for lid, e in self.lost.items() if e.expiry_batch <= current_batch]
        for lid in expired:
            del self.lost[lid]
        return expired
