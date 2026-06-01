import json
import logging
from typing import Iterator, Tuple

import boto3
import cv2
import numpy as np
import redis as redis_lib

log = logging.getLogger("iep2.redis_source")

STREAM_PREFIX = "stream:iep1"


def make_s3_client(endpoint_url: str, access_key: str, secret_key: str):
    kwargs = dict(
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name="us-east-1",
    )
    if endpoint_url:
        kwargs["endpoint_url"] = endpoint_url
    return boto3.client("s3", **kwargs)


class RedisStreamFrameSource:
    def __init__(self, camera_id: str, redis_url: str, s3_client, s3_bucket: str) -> None:
        self._camera_id = camera_id
        self._s3_client = s3_client
        self._s3_bucket = s3_bucket
        self._stream_name = f"{STREAM_PREFIX}:{camera_id}"
        self._redis = redis_lib.Redis.from_url(redis_url)
        self._stop = False
        self._last_id = "$"

    def frames(self) -> Iterator[Tuple[int, np.ndarray]]:
        while not self._stop:
            response = self._redis.xread(
                {self._stream_name: self._last_id},
                block=2000,
                count=1,
            )
            if not response:
                continue

            for _stream, messages in response:
                for msg_id, fields in messages:
                    self._last_id = msg_id

                    raw = fields.get(b"manifest") or fields.get("manifest")
                    if raw is None:
                        continue

                    manifest = json.loads(raw)

                    if manifest.get("status") == "offline":
                        log.debug(
                            "camera_id=%s: skipping offline window batch=%s",
                            self._camera_id, manifest.get("batch_number"),
                        )
                        continue

                    for frame_entry in manifest.get("frames", []):
                        if self._stop:
                            return
                        capture_ts_ms = int(frame_entry[0])
                        s3_key = frame_entry[1]

                        try:
                            s3_resp = self._s3_client.get_object(
                                Bucket=self._s3_bucket,
                                Key=s3_key,
                            )
                            data = s3_resp["Body"].read()
                        except Exception as exc:
                            log.warning(
                                "camera_id=%s: S3 fetch failed key=%s: %s",
                                self._camera_id, s3_key, exc,
                            )
                            continue

                        arr = np.frombuffer(data, dtype=np.uint8)
                        frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                        if frame is None:
                            log.warning(
                                "camera_id=%s: imdecode failed key=%s",
                                self._camera_id, s3_key,
                            )
                            continue

                        yield capture_ts_ms, s3_key, frame

    def release(self) -> None:
        self._stop = True


# ---------------------------------------------------------------------------
# Standalone: python IEP2/ingest/redis_source.py
# Requires Redis running with at least one IEP1 manifest in stream:iep1:test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import os
    import sys
    from dotenv import load_dotenv

    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    redis_url  = os.environ.get("REDIS_URL",       "redis://localhost:6379/0")
    endpoint   = os.environ.get("S3_ENDPOINT_URL", "")
    access_key = os.environ.get("S3_ACCESS_KEY",   "")
    secret_key = os.environ.get("S3_SECRET_KEY",   "")
    bucket     = os.environ.get("S3_BUCKET",       "retailvision")

    s3 = make_s3_client(endpoint, access_key, secret_key)
    source = RedisStreamFrameSource(
        camera_id="test",
        redis_url=redis_url,
        s3_client=s3,
        s3_bucket=bucket,
    )

    count = 0
    for ts, frame in source.frames():
        print(f"frame capture_ts_ms={ts} shape={frame.shape}")
        count += 1
        if count >= 1:
            break

    source.release()
    print(f"frame_count={count}")
