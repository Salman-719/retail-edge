import logging
import os
import time
from typing import Optional

import boto3
import cv2
import numpy as np

logger = logging.getLogger(__name__)

JPEG_QUALITY = 85
UPLOAD_RETRY_ATTEMPTS = 3
UPLOAD_RETRY_DELAY_SECONDS = 1.0
S3_KEY_PREFIX = "frames"


class S3Uploader:
    def __init__(self, camera_id: str, bucket: str, s3_client=None) -> None:
        self.camera_id = camera_id
        self.bucket = bucket
        self._client = s3_client if s3_client is not None else self._build_client()

    @staticmethod
    def _build_client():
        kwargs = {
            "aws_access_key_id": os.environ.get("S3_ACCESS_KEY"),
            "aws_secret_access_key": os.environ.get("S3_SECRET_KEY"),
        }
        endpoint = os.environ.get("S3_ENDPOINT_URL")
        if endpoint:
            kwargs["endpoint_url"] = endpoint
        return boto3.client("s3", **kwargs)

    def upload(self, capture_ts_ms: int, frame: np.ndarray) -> Optional[str]:
        try:
            ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
        except cv2.error as exc:
            logger.error("camera_id=%s: JPEG encoding raised: %s", self.camera_id, exc)
            return None
        if not ok:
            logger.error("camera_id=%s: JPEG encoding failed, skipping upload", self.camera_id)
            return None

        key = f"{S3_KEY_PREFIX}/{self.camera_id}/{capture_ts_ms}.jpg"
        data = buf.tobytes()

        for attempt in range(1, UPLOAD_RETRY_ATTEMPTS + 1):
            try:
                self._client.put_object(
                    Bucket=self.bucket,
                    Key=key,
                    Body=data,
                    ContentType="image/jpeg",
                )
                return key
            except Exception as exc:
                logger.warning(
                    "camera_id=%s: upload attempt %d/%d failed: %s",
                    self.camera_id,
                    attempt,
                    UPLOAD_RETRY_ATTEMPTS,
                    exc,
                )
                if attempt < UPLOAD_RETRY_ATTEMPTS:
                    time.sleep(UPLOAD_RETRY_DELAY_SECONDS)

        logger.error(
            "camera_id=%s: all %d upload attempts exhausted for key %s",
            self.camera_id,
            UPLOAD_RETRY_ATTEMPTS,
            key,
        )
        return None


    def delete_keys(self, keys: list) -> None:
        if not keys:
            return
        chunk_size = 1000
        total_deleted = 0
        for i in range(0, len(keys), chunk_size):
            chunk = keys[i : i + chunk_size]
            objects = [{"Key": k} for k in chunk]
            try:
                self._client.delete_objects(
                    Bucket=self.bucket,
                    Delete={"Objects": objects, "Quiet": True},
                )
                total_deleted += len(chunk)
            except Exception as exc:
                logger.error(
                    "camera_id=%s: delete_objects failed for %d keys: %s",
                    self.camera_id,
                    len(chunk),
                    exc,
                )
        if total_deleted:
            logger.info("camera_id=%s: deleted %d keys from S3", self.camera_id, total_deleted)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    bucket = os.environ.get("S3_BUCKET", "retailvision")
    uploader = S3Uploader(camera_id="test-cam", bucket=bucket)

    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    frame[:] = (120, 80, 200)  # solid color so encode is non-trivial

    capture_ts_ms = int(time.time() * 1000)
    key = uploader.upload(capture_ts_ms, frame)

    if key is None:
        print("FAIL: upload returned None")
        raise SystemExit(1)

    print(f"Uploaded key: {key}")

    # Confirm object exists
    try:
        uploader._client.head_object(Bucket=bucket, Key=key)
        print("OK")
    except Exception as exc:
        print(f"FAIL: head_object check failed: {exc}")
        raise SystemExit(1)
