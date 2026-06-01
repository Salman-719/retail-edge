"""Async S3 helper shared by IAIP1 edge upload and cloud-side frame reads."""

from __future__ import annotations

import asyncio
import os
from typing import Any

import numpy as np

from common.config import Settings, get_settings


class S3Client:
    """Small boto3 wrapper that keeps blocking S3 calls off the event loop."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._s = settings or get_settings()
        self._client: Any | None = None

    @property
    def bucket(self) -> str:
        return self._s.S3_BUCKET

    def _get_client(self) -> Any:
        if self._client is None:
            try:
                import boto3
            except Exception as exc:
                raise RuntimeError("boto3 is required for S3 frame storage") from exc

            kwargs: dict[str, Any] = {
                "endpoint_url": self._s.S3_ENDPOINT_URL or os.getenv("S3_ENDPOINT_URL") or None,
                "region_name": self._s.AWS_REGION or os.getenv("AWS_REGION") or None,
                "aws_access_key_id": self._s.S3_ACCESS_KEY or os.getenv("S3_ACCESS_KEY") or None,
                "aws_secret_access_key": self._s.S3_SECRET_KEY or os.getenv("S3_SECRET_KEY") or None,
                "aws_session_token": self._s.AWS_SESSION_TOKEN or os.getenv("AWS_SESSION_TOKEN") or None,
            }
            self._client = boto3.client("s3", **kwargs)
        return self._client

    async def ensure_bucket(self) -> None:
        def _ensure() -> None:
            client = self._get_client()
            try:
                client.head_bucket(Bucket=self.bucket)
            except Exception:
                client.create_bucket(Bucket=self.bucket)

        await asyncio.to_thread(_ensure)

    async def put_bytes(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        def _put() -> None:
            self._get_client().put_object(
                Bucket=self.bucket,
                Key=key,
                Body=data,
                ContentType=content_type,
            )

        await asyncio.to_thread(_put)
        return f"s3://{self.bucket}/{key}"

    async def get_bytes(self, key: str, bucket: str | None = None) -> bytes:
        return await asyncio.to_thread(self.get_bytes_sync, key, bucket)

    def get_bytes_sync(self, key: str, bucket: str | None = None) -> bytes:
        body = self._get_client().get_object(Bucket=bucket or self.bucket, Key=key)["Body"]
        return body.read()

    async def get_image(self, key: str, bucket: str | None = None) -> Any:
        import cv2

        body = await self.get_bytes(key, bucket=bucket)
        image = np.frombuffer(body, dtype=np.uint8)
        frame = cv2.imdecode(image, cv2.IMREAD_COLOR)
        if frame is None:
            raise RuntimeError(f"Unable to decode S3 image: s3://{bucket or self.bucket}/{key}")
        return frame
