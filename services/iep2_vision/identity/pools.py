"""Data structures for the identity pipeline.

Three dataclasses only — no logic, no methods beyond __init__.
Steps 4 and 5 extend these without modifying this file.
"""
from dataclasses import dataclass, field

try:
    from .gallery import EmbeddingGallery
except ImportError:
    import sys as _sys, os as _os
    _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
    from gallery import EmbeddingGallery


@dataclass
class ActiveTrack:
    local_id: int
    track_id: int
    gallery: EmbeddingGallery
    last_floor_pos: tuple[float, float] | None = None
    # Crops buffered during init phase — flushed to ReID as a batch once full.
    # Each entry is (crop_ndarray, bbox, timestamp_ms).
    init_crops: list = field(default_factory=list)


@dataclass
class PendingTrack:
    track_id: int
    init_embeddings: list = field(default_factory=list)
    # Raw crops buffered until we have a full batch to send to ReID at once.
    # Each entry is (frame_ndarray, bbox, timestamp_ms).
    init_crops: list = field(default_factory=list)


@dataclass
class LostEntry:
    local_id: int
    lost_at_frame: int  # TTL anchor used in Step 4
    gallery: EmbeddingGallery
    last_floor_pos: tuple[float, float] | None = None
