"""Identity state enums and batch-event payloads."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class TrackState(str, Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    LOST = "lost"


class GlobalState(str, Enum):
    ACTIVE = "active"
    LOST = "lost"
    EXITED = "exited"


@dataclass(frozen=True)
class BatchCompleteEvent:
    """Emitted by IEP2 when a camera finishes a batch; consumed by the
    coordinator that triggers IEP3."""

    store_id: str
    camera_id: str
    batch_number: int
    window_start_ms: int
    window_end_ms: int
