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


@dataclass
class PendingTrack:
    track_id: int
    init_embeddings: list = field(default_factory=list)  # filled in Step 4


@dataclass
class LostEntry:
    local_id: int
    lost_at_frame: int  # TTL anchor used in Step 4
    gallery: EmbeddingGallery
