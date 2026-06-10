import collections
import logging
import time
from dataclasses import dataclass

from services.iep1_ingestion.app.source.rtsp_source import RtspSource
from services.iep1_ingestion.app.uploader import S3Uploader
from services.iep1_ingestion.app.window import WindowAccumulator
from services.iep1_ingestion.app.publisher import WindowPublisher

logger = logging.getLogger(__name__)

BATCH_TTL_SECONDS = 300


def now_ms() -> int:
    return int(time.time() * 1000)


@dataclass
class Iep1Settings:
    store_id:             str
    camera_id:            str
    rtsp_url:             str | None = None
    target_fps:           float = 5.0
    batch_window_seconds: float = 60.0
    s3_bucket:            str   = "retailvision"
    redis_url:            str   = "redis://localhost:6379/0"


class Iep1Runtime:
    def __init__(self, settings: Iep1Settings, source=None) -> None:
        self._settings = settings
        self._source = source or RtspSource(
            settings.rtsp_url,
            settings.target_fps,
            settings.camera_id,
        )
        self._uploader = S3Uploader(settings.camera_id, settings.s3_bucket)
        self._accumulator = WindowAccumulator(
            settings.target_fps,
            settings.batch_window_seconds,
        )
        self._publisher = WindowPublisher(settings.camera_id, settings.redis_url)
        self._batch_number = 0
        self._pending_cleanup: collections.deque = collections.deque()

    def _close_window(self, window_start_ms: int) -> None:
        window_end_ms = now_ms()
        manifest = self._accumulator.close(window_start_ms, window_end_ms, self._batch_number)
        logger.info(
            "camera_id=%s batch=%d status=%s frames=%d/%d gaps=%d",
            self._settings.camera_id,
            self._batch_number,
            manifest.status,
            manifest.frame_count,
            manifest.expected_frames,
            len(manifest.gaps),
        )
        self._publisher.publish(manifest)
        self._accumulator.reset()
        keys = [frame[1] for frame in manifest.frames]
        if keys:
            self._pending_cleanup.append((now_ms(), keys))
        self._batch_number += 1

    def _flush_expired_batches(self) -> None:
        cutoff_ms = now_ms() - BATCH_TTL_SECONDS * 1000
        while self._pending_cleanup and self._pending_cleanup[0][0] <= cutoff_ms:
            _, keys = self._pending_cleanup.popleft()
            self._uploader.delete_keys(keys)

    def run(self) -> None:
        window_start_ms = now_ms()
        batch_duration_ms = self._settings.batch_window_seconds * 1000

        try:
            for capture_ts_ms, frame in self._source.frames():
                key = self._uploader.upload(capture_ts_ms, frame)
                if key is not None:
                    self._accumulator.add(capture_ts_ms, key)
                    logger.debug("camera_id=%s uploaded %s", self._settings.camera_id, key)
                else:
                    logger.debug(
                        "camera_id=%s upload failed for ts=%d, skipping",
                        self._settings.camera_id,
                        capture_ts_ms,
                    )

                self._flush_expired_batches()

                if now_ms() - window_start_ms >= batch_duration_ms:
                    self._close_window(window_start_ms)
                    window_start_ms = now_ms()
        finally:
            self._close_window(window_start_ms)
            self._flush_expired_batches()
            # Unconditional cleanup of all remaining batches on exit
            while self._pending_cleanup:
                _, keys = self._pending_cleanup.popleft()
                self._uploader.delete_keys(keys)
            self._source.release()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    settings = Iep1Settings(
        store_id="smoke-store",
        camera_id="smoke-cam",
        rtsp_url="rtsp://localhost:8554/nonexistent",
    )
    runtime = Iep1Runtime(settings)
    print("Iep1Runtime OK")
