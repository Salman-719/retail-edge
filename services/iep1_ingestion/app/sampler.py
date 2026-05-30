"""Sampler -- thin pass-through over a FrameSource.

The source already decimates to ``sample_rate_fps`` and stamps capture time
(video mode) or will do so from wall-clock (RTSP mode), so the sampler is a thin
iterator today. It is the seam where the RTSP **recovery wrapper** (backoff +
reconnect around source iteration) will live, keeping that concern out of both
the source and the runtime.
"""

from __future__ import annotations

from collections.abc import Iterator

import numpy as np

from services.iep1_ingestion.app.source.base import FrameSource


class Sampler:
    def __init__(self, source: FrameSource, sample_rate_fps: float):
        self._source = source
        self._fps = sample_rate_fps

    def sampled(self) -> Iterator[tuple[int, np.ndarray]]:
        yield from self._source.frames()
