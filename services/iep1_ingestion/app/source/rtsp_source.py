"""RTSP frame source -- production seam (stub).

In production this pulls frames from an RTSP stream, stamping each with the
wall-clock (NTP-synced) time it was pulled, and handles disconnect/backoff
reconnect inside ``frames()`` so the rest of IEP1 is unchanged. Implemented when
live ingestion lands; the ``FrameSource`` protocol is the only contract it must
satisfy.
"""

from __future__ import annotations

from collections.abc import Iterator

import numpy as np


class RtspSource:
    def __init__(self, rtsp_url: str, target_fps: float):
        self._url = rtsp_url
        self._target = target_fps

    def frames(self) -> Iterator[tuple[int, np.ndarray]]:  # pragma: no cover - production seam
        raise NotImplementedError(
            "RtspSource is a production seam; use VideoFileSource until live ingestion lands."
        )

    def is_available(self) -> bool:  # pragma: no cover - production seam
        return False
