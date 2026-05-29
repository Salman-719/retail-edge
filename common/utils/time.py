"""Epoch-ms time helpers."""

from __future__ import annotations

import time


def now_ms() -> int:
    """Current wall-clock time in epoch milliseconds."""
    return int(time.time() * 1000)


def ms_to_seconds(ms: int) -> float:
    return ms / 1000.0
