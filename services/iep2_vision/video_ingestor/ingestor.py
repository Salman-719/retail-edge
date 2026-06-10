"""Video ingestor — sole owner of: receive video, emit frames at 5fps.

Swap OpenCV for another decoder here and nothing outside this file changes.
"""
import sys
from typing import Generator

import cv2
import numpy as np

TARGET_FPS = 5


def extract_frames(video_path: str) -> Generator[np.ndarray, None, None]:
    """Read `video_path` and yield raw BGR numpy frames resampled to 5fps.

    Resampling is done by selecting frames whose source index crosses the
    next 1/TARGET_FPS-second boundary, so the output is exactly ~5fps
    regardless of the source frame rate.
    """
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise IOError(f"Cannot open video: {video_path}")

    try:
        src_fps = cap.get(cv2.CAP_PROP_FPS)
        if not src_fps or src_fps <= 0:
            src_fps = TARGET_FPS  # fall back: treat every frame as a sample

        # How many source frames per emitted frame.
        step = src_fps / TARGET_FPS

        src_index = 0
        next_emit = 0.0
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            if src_index >= next_emit:
                yield frame
                next_emit += step
            src_index += 1
    finally:
        cap.release()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: python ingestor.py <video_path>")
        sys.exit(1)

    count = sum(1 for _ in extract_frames(sys.argv[1]))
    print(f"frames extracted at {TARGET_FPS}fps: {count}")
