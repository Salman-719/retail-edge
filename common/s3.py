"""Shared S3 / object-storage client for the IEP subsystem.

IEP1 writes JPEG frames here; IEP2 reads them back by key. Wraps the **sync**
boto3 client (the dependency EEP already uses) in ``asyncio.to_thread`` so async
call sites never block the event loop on network I/O — no new heavy async-S3
dependency is introduced.

Construct one per worker (``S3Client()``); it is cheap and DI-friendly so tests
can substitute an in-memory fake (see ``tests/fakes.py``). Reuses the EEP-style
``S3_*`` settings from ``common.config``.
"""

from __future__ import annotations

import asyncio

import numpy as np

from common.config import get_settings


class S3Client:
    def __init__(self, settings=None):
        self._s = settings or get_settings()
        self._client = None  # lazy: created on first use (and inside the worker thread context)

    # ---- sync internals (run inside asyncio.to_thread) ----

    def _get_client(self):
        if self._client is None:
            import boto3

            self._client = boto3.client(
                "s3",
                endpoint_url=self._s.S3_ENDPOINT_URL,
                aws_access_key_id=self._s.S3_ACCESS_KEY,
                aws_secret_access_key=self._s.S3_SECRET_KEY,
            )
        return self._client

    def _put_bytes(self, key: str, data: bytes, content_type: str) -> None:
        self._get_client().put_object(
            Bucket=self._s.S3_BUCKET, Key=key, Body=data, ContentType=content_type
        )

    def _get_bytes(self, key: str) -> bytes | None:
        from botocore.exceptions import ClientError

        try:
            resp = self._get_client().get_object(Bucket=self._s.S3_BUCKET, Key=key)
            return resp["Body"].read()
        except ClientError:
            return None

    def _ensure_bucket(self) -> None:
        from botocore.exceptions import ClientError

        client = self._get_client()
        try:
            client.head_bucket(Bucket=self._s.S3_BUCKET)
        except ClientError:
            client.create_bucket(Bucket=self._s.S3_BUCKET)

    # ---- async API ----

    async def put_bytes(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
        await asyncio.to_thread(self._put_bytes, key, data, content_type)

    async def get_bytes(self, key: str) -> bytes | None:
        return await asyncio.to_thread(self._get_bytes, key)

    async def get_image(self, key: str) -> np.ndarray | None:
        """Fetch a key and decode it to a BGR image. Returns None if the key is
        missing or the bytes don't decode."""
        data = await self.get_bytes(key)
        if not data:
            return None
        import cv2

        arr = np.frombuffer(data, dtype=np.uint8)
        return cv2.imdecode(arr, cv2.IMREAD_COLOR)

    async def ensure_bucket(self) -> None:
        await asyncio.to_thread(self._ensure_bucket)
