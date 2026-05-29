"""Groups the continuous SampledFrame stream into fixed-duration batches.

The tracker stays continuous across batch boundaries (frames are fed in order
regardless of batch); the batcher only marks where one batch ends and the next
begins, so persistence flushes and ``batch_complete`` events fire at the right
points.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator

from services.iep2_vision.app.ingest.video_source import SampledFrame


class Batcher:
    """Yields ``(batch_number, list[SampledFrame])``. A batch closes when the
    accumulated sampled frame count reaches ``batch_window_seconds * target_fps``."""

    def __init__(self, source: Iterable[SampledFrame], batch_window_seconds: int, target_fps: float):
        self._source = source
        self._frames_per_batch = max(1, int(batch_window_seconds * target_fps))

    def __iter__(self) -> Iterator[tuple[int, list[SampledFrame]]]:
        batch_number, buf = 0, []
        for sf in self._source:
            buf.append(sf)
            if len(buf) >= self._frames_per_batch:
                yield batch_number, buf
                batch_number += 1
                buf = []
        if buf:
            yield batch_number, buf  # final partial batch
