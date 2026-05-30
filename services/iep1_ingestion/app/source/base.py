"""FrameSource protocol -- the production seam.

The ONLY thing that differs between video-file mode (now) and RTSP mode (later).
Everything downstream (sampler, uploader, window, publisher) is identical.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Protocol

import numpy as np


class FrameSource(Protocol):
    def frames(self) -> Iterator[tuple[int, np.ndarray]]:
        """Yields ``(capture_ts_ms, frame_bgr)`` for each delivered frame."""
        ...

    def is_available(self) -> bool:
        """False when the source has dropped (RTSP) or ended (video)."""
        ...
