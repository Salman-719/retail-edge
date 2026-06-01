import logging
import time
from typing import Iterator, Tuple

import cv2
import numpy as np

logger = logging.getLogger(__name__)

RECONNECT_ATTEMPTS = 5
RECONNECT_DELAY_SECONDS = 3.0
READ_TIMEOUT_SECONDS = 10.0


class RtspSource:
    def __init__(self, rtsp_url: str, target_fps: float, camera_id: str) -> None:
        self.rtsp_url = rtsp_url
        self.target_fps = target_fps
        self.camera_id = camera_id
        self._cap: cv2.VideoCapture | None = None
        self._available: bool = False

    def _open(self) -> bool:
        cap = cv2.VideoCapture(self.rtsp_url)
        if not cap.isOpened():
            cap.release()
            return False
        self._cap = cap
        self._available = True
        return True

    def _decimation_ratio(self) -> int:
        assert self._cap is not None
        source_fps = self._cap.get(cv2.CAP_PROP_FPS)
        if not source_fps or source_fps <= 0:
            logger.warning(
                "camera_id=%s: could not read source fps, defaulting decimation N=1",
                self.camera_id,
            )
            return 1
        return max(1, round(source_fps / self.target_fps))

    def frames(self) -> Iterator[Tuple[int, np.ndarray]]:
        if self._cap is None:
            if not self._open():
                logger.error("camera_id=%s: initial connection failed", self.camera_id)
                return

        assert self._cap is not None
        n = self._decimation_ratio()
        frame_index = 0

        while True:
            ret, frame = self._cap.read()

            if not ret:
                # Attempt reconnect
                reconnected = False
                for attempt in range(1, RECONNECT_ATTEMPTS + 1):
                    logger.warning(
                        "camera_id=%s: read failed, reconnect attempt %d/%d",
                        self.camera_id,
                        attempt,
                        RECONNECT_ATTEMPTS,
                    )
                    if self._cap is not None:
                        self._cap.release()
                    self._cap = None
                    self._available = False
                    time.sleep(RECONNECT_DELAY_SECONDS)
                    if self._open():
                        n = self._decimation_ratio()
                        frame_index = 0
                        reconnected = True
                        break

                if not reconnected:
                    logger.error(
                        "camera_id=%s: all %d reconnect attempts exhausted, stopping",
                        self.camera_id,
                        RECONNECT_ATTEMPTS,
                    )
                    return

                continue

            if frame_index % n == 0:
                capture_ts_ms = int(time.time() * 1000)
                yield capture_ts_ms, frame

            frame_index += 1

    def is_available(self) -> bool:
        return self._available

    def release(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None
        self._available = False


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    if len(sys.argv) < 3:
        print("Usage: python -m services.iep1_ingestion.app.source.rtsp_source <rtsp_url> <target_fps>")
        sys.exit(1)

    url = sys.argv[1]
    fps = float(sys.argv[2])
    source = RtspSource(rtsp_url=url, target_fps=fps, camera_id="cli-test")

    count = 0
    for ts, frame in source.frames():
        print(f"frame {count + 1}: capture_ts_ms={ts} shape={frame.shape}")
        count += 1
        if count >= 10:
            break

    source.release()
    source.release()  # verify double-release is safe
    print("Done — released cleanly")
