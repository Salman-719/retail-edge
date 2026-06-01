from __future__ import annotations

from typing import Any

import numpy as np

from common.s3 import S3Client
from services.iep2_vision.app.vision_events import FrameRefEvent


class FrameResolver:
    def __init__(self) -> None:
        self._captures: dict[str, Any] = {}

    def read(self, event: FrameRefEvent) -> Any:
        import cv2

        uri = event.frame_ref.uri
        if uri.startswith("s3://"):
            return self._read_s3_image(cv2, uri)

        path = uri.removeprefix("file://")
        frame_index = event.frame_ref.frame_index
        if frame_index is None:
            frame = cv2.imread(path)
            if frame is None:
                raise RuntimeError(f"Unable to read frame image: {uri}")
            return frame

        cap = self._captures.get(path)
        if cap is None:
            cap = cv2.VideoCapture(path)
            if not cap.isOpened():
                raise RuntimeError(f"Unable to open frame source: {uri}")
            self._captures[path] = cap

        cap.set(cv2.CAP_PROP_POS_FRAMES, int(frame_index))
        ok, frame = cap.read()
        if not ok:
            raise RuntimeError(f"Unable to read frame {frame_index} from {uri}")
        return frame

    def _read_s3_image(self, cv2: Any, uri: str) -> Any:
        without_scheme = uri.removeprefix("s3://")
        bucket, _, key = without_scheme.partition("/")
        if not bucket or not key:
            raise RuntimeError(f"Invalid s3 frame ref: {uri}")
        client = S3Client()
        body = client.get_bytes_sync(key, bucket=bucket)
        image = np.frombuffer(body, dtype=np.uint8)
        frame = cv2.imdecode(image, cv2.IMREAD_COLOR)
        if frame is None:
            raise RuntimeError(f"Unable to decode s3 frame ref: {uri}")
        return frame

    def close(self) -> None:
        for cap in self._captures.values():
            cap.release()
        self._captures.clear()
