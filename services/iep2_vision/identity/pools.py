"""Data structures for the identity pipeline.

Three dataclasses only — no logic, no methods beyond __init__.
Steps 4 and 5 extend these without modifying this file.
"""
from dataclasses import dataclass, field


@dataclass
class ActiveTrack:
    local_id: int
    track_id: int


@dataclass
class PendingTrack:
    track_id: int
    init_embeddings: list = field(default_factory=list)  # filled in Step 4


@dataclass
class LostEntry:
    local_id: int
    lost_at_frame: int  # TTL anchor used in Step 4
