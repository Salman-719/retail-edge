"""Video chunk assembler for IEP1.

Splits uploaded videos into fixed-duration chunks with configurable overlap,
applying frame quality filters before upload to S3.
"""
import os
import logging
from pathlib import Path
from typing import List, Dict

import cv2

from app.utils.quality import check_frame
from app.core.s3_client import s3_client
from app.core.config import settings

logger = logging.getLogger(__name__)

CHUNK_DURATION = 300    # 5 minutes in seconds
OVERLAP = 30            # 30 seconds overlap between consecutive chunks


class ChunkResult:
    def __init__(self, chunk_idx: int, s3_key: str, start_sec: float, end_sec: float,
                 total_frames: int, accepted_frames: int, rejected_frames: int):
        self.chunk_idx = chunk_idx
        self.s3_key = s3_key
        self.start_sec = start_sec
        self.end_sec = end_sec
        self.total_frames = total_frames
        self.accepted_frames = accepted_frames
        self.rejected_frames = rejected_frames

    def to_dict(self) -> dict:
        return {
            "chunk_idx": self.chunk_idx,
            "s3_key": self.s3_key,
            "start_sec": self.start_sec,
            "end_sec": self.end_sec,
            "total_frames": self.total_frames,
            "accepted_frames": self.accepted_frames,
            "rejected_frames": self.rejected_frames,
        }


def chunk_video(
    video_path: str,
    store_id: str,
    camera_id: str,
    chunk_duration: int = CHUNK_DURATION,
    overlap: int = OVERLAP,
    apply_quality_filter: bool = True,
) -> List[ChunkResult]:
    """Split a video file into chunks and upload each to S3.

    Args:
        video_path: Local path to the video file.
        store_id: Store ID for S3 key prefix.
        camera_id: Camera ID for S3 key prefix.
        chunk_duration: Duration of each chunk in seconds.
        overlap: Overlap in seconds between consecutive chunks.
        apply_quality_filter: Whether to run frame quality checks.

    Returns:
        List of ChunkResult with S3 keys and metadata.
    """
    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    total_frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration = total_frame_count / fps

    if duration <= chunk_duration:
        # Video is shorter than one chunk — return as single chunk
        cap.release()
        s3_key = f"stores/{store_id}/cameras/{camera_id}/chunks/chunk_000.mp4"
        s3_client.upload_file(s3_key, video_path, content_type="video/mp4")
        return [ChunkResult(
            chunk_idx=0, s3_key=s3_key,
            start_sec=0.0, end_sec=duration,
            total_frames=total_frame_count,
            accepted_frames=total_frame_count,
            rejected_frames=0,
        )]

    results: List[ChunkResult] = []
    chunk_idx = 0
    start_sec = 0.0

    while start_sec < duration:
        end_sec = min(start_sec + chunk_duration + overlap, duration)
        start_frame = int(start_sec * fps)
        end_frame = int(end_sec * fps)

        # Write chunk to temp file
        tmp_dir = settings.TMP_DIR
        os.makedirs(tmp_dir, exist_ok=True)
        chunk_path = os.path.join(tmp_dir, f"chunk_{camera_id}_{chunk_idx}.mp4")

        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(chunk_path, fourcc, fps, (
            int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
            int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
        ))

        cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
        frame_count = 0
        accepted = 0
        rejected = 0
        prev_frame = None

        for _ in range(end_frame - start_frame):
            ret, frame = cap.read()
            if not ret:
                break
            frame_count += 1

            if apply_quality_filter:
                reason = check_frame(frame, prev_frame)
                prev_frame = frame
                if reason:
                    rejected += 1
                    continue
                accepted += 1
            else:
                accepted += 1

            writer.write(frame)

        writer.release()

        # Upload chunk to S3
        s3_key = f"stores/{store_id}/cameras/{camera_id}/chunks/chunk_{chunk_idx:03d}.mp4"
        s3_client.upload_file(s3_key, chunk_path, content_type="video/mp4")
        os.remove(chunk_path)

        results.append(ChunkResult(
            chunk_idx=chunk_idx,
            s3_key=s3_key,
            start_sec=start_sec,
            end_sec=end_sec,
            total_frames=frame_count,
            accepted_frames=accepted,
            rejected_frames=rejected,
        ))

        logger.info(
            f"Chunk {chunk_idx}: {start_sec:.1f}-{end_sec:.1f}s, "
            f"{accepted}/{frame_count} frames accepted"
        )

        chunk_idx += 1
        start_sec += chunk_duration  # next chunk starts after duration (not overlap)

    cap.release()
    return results
