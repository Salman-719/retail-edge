"""Iep1Runtime -- assembles source -> sampler -> uploader -> window -> publisher.

**Capture-time-driven windowing (video mode).** A window closes when a frame's
capture timestamp crosses ``window_start + batch_window_seconds*1000``. This runs
as-fast-as-possible (no real-time wait), is deterministic, and aligns batches to
capture-time content -- the same time-bounded semantics as IEP2's batcher. If the
capture clock jumps across several window boundaries (a long gap), the intervening
windows are closed in order so ``batch_number`` stays monotonic and dense; those
empty windows naturally classify as offline/degraded. At EOF the final partial
window is closed and published, then the worker exits.

> **RTSP / live seam:** production drives windows from a wall-clock timer
> (``asyncio.sleep(batch_window_seconds)``) running concurrently with the frame
> loop, so a *dead* camera still emits offline batches on schedule even though no
> frames arrive. That variant is documented here and belongs with ``RtspSource``;
> the capture-time loop below is the file-mode equivalent (a finite source can't
> "hang", so its empty windows are derived from the capture clock instead).
"""

from __future__ import annotations

import logging

from services.iep1_ingestion.app import health
from services.iep1_ingestion.app.publisher import WindowPublisher
from services.iep1_ingestion.app.sampler import Sampler
from services.iep1_ingestion.app.uploader import S3Uploader
from services.iep1_ingestion.app.window import WindowAccumulator

log = logging.getLogger(__name__)


class Iep1Runtime:
    def __init__(self, store_id, camera_id, settings, *, s3_client=None, redis_client=None):
        self._store, self._cam, self._s = store_id, camera_id, settings
        self._s3_client = s3_client
        self._redis_client = redis_client

    async def run(self, source, start_epoch_ms: int) -> dict:
        sampler = Sampler(source, self._s.sample_rate_fps)
        uploader = S3Uploader(self._cam, self._s, s3_client=self._s3_client)
        window = WindowAccumulator(
            self._cam, self._store, self._s.batch_window_seconds * 1000,
            self._s.sample_rate_fps, self._s,
        )
        publisher = WindowPublisher(self._cam, redis_client=self._redis_client, settings=self._s)

        window_ms = self._s.batch_window_seconds * 1000
        batch_number = 0
        window_start = start_epoch_ms
        published = 0

        async def close_and_publish(w_start: int, w_end: int, bn: int) -> None:
            nonlocal published
            manifest = window.close(w_start, w_end, bn)
            await publisher.publish(manifest)
            health.emit_health(manifest)
            published += 1

        for capture_ts, frame in sampler.sampled():
            # Close every window the capture clock has fully passed (keeps
            # batch_number monotonic + dense across gaps).
            while capture_ts >= window_start + window_ms:
                w_end = window_start + window_ms
                await close_and_publish(window_start, w_end, batch_number)
                batch_number += 1
                window_start = w_end

            key = await uploader.upload(capture_ts, frame)
            if key:
                window.add(capture_ts, key)
                health.frames_captured.labels(self._cam).inc()
            else:
                health.frames_dropped.labels(self._cam, "s3_fail").inc()

        # Final partial window at EOF (always emitted, even if empty).
        await close_and_publish(window_start, window_start + window_ms, batch_number)
        return {"batches_published": published, "last_batch_number": batch_number}
