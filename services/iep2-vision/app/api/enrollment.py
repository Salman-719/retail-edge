"""Employee ReID enrollment endpoint.

Extracts appearance embeddings from an enrollment video and stores them.
"""
import os
import logging
from pathlib import Path

import cv2
import numpy as np
import sqlalchemy as sa
from fastapi import APIRouter, HTTPException

from app.schemas import EnrollmentRequest, EnrollmentResponse
from app.core.config import settings
from app.core.s3_client import s3_client
from app.core.database import AsyncSessionLocal
from app.utils.reid import ReIDExtractor

logger = logging.getLogger(__name__)
router = APIRouter()

_reid: ReIDExtractor | None = None


def _get_reid() -> ReIDExtractor:
    global _reid
    if _reid is None:
        _reid = ReIDExtractor()
    return _reid


@router.post(
    "/enrollment/{store_id}/employees/{employee_id}/enroll",
    response_model=EnrollmentResponse,
)
async def enroll_employee(
    store_id: str,
    employee_id: str,
    payload: EnrollmentRequest,
):
    """Extract ReID embeddings from enrollment video and store as gallery.

    Process:
    1. Download video from S3
    2. Run YOLO person detection on sampled frames
    3. Extract ReID embeddings from detected person crops
    4. Average embeddings into a gallery vector
    5. Store in employees.gallery_embeddings
    """
    from ultralytics import YOLO

    tmp_dir = settings.TMP_DIR
    os.makedirs(tmp_dir, exist_ok=True)
    ext = Path(payload.video_s3_key).suffix or ".mp4"
    tmp_path = os.path.join(tmp_dir, f"enroll_{employee_id}{ext}")

    try:
        s3_client.download_to_file(payload.video_s3_key, tmp_path)
    except Exception as e:
        raise HTTPException(404, f"Could not download video: {e}")

    try:
        cap = cv2.VideoCapture(tmp_path)
        fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

        model = YOLO("yolov8n.pt")
        reid = _get_reid()
        sample_every = max(1, total_frames // payload.sample_count)

        embeddings = []
        frame_idx = 0

        while True:
            ret, frame = cap.read()
            if not ret:
                break

            if frame_idx % sample_every == 0:
                results = model(frame, classes=[0], conf=0.5, verbose=False)
                boxes = results[0].boxes.xyxy.cpu().numpy() if results[0].boxes else []

                if len(boxes) > 0:
                    # Take the largest detection (most likely the enrollment subject)
                    areas = (boxes[:, 2] - boxes[:, 0]) * (boxes[:, 3] - boxes[:, 1])
                    best_idx = int(areas.argmax())
                    box = boxes[best_idx].astype(int)
                    crop = frame[box[1]:box[3], box[0]:box[2]]

                    emb = reid.extract(crop)
                    if emb is not None:
                        embeddings.append(emb)

            frame_idx += 1

        cap.release()

        if not embeddings:
            return EnrollmentResponse(
                employee_id=employee_id,
                status="failed",
                error="No valid person crops extracted from video",
            )

        # Average embeddings and normalize
        gallery_emb = np.mean(embeddings, axis=0)
        gallery_emb = gallery_emb / (np.linalg.norm(gallery_emb) + 1e-8)

        # Store in DB
        async with AsyncSessionLocal() as session:
            await session.execute(
                sa.text(
                    "UPDATE employees SET gallery_embeddings = :emb WHERE id = :id"
                ),
                {"emb": gallery_emb.tolist(), "id": employee_id},
            )
            await session.commit()

        return EnrollmentResponse(
            employee_id=employee_id,
            status="enrolled",
            embedding_dim=len(gallery_emb),
            samples_extracted=len(embeddings),
        )

    except Exception as e:
        logger.exception(f"Enrollment failed for {employee_id}")
        return EnrollmentResponse(
            employee_id=employee_id,
            status="failed",
            error=str(e),
        )

    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
