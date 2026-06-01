import asyncio
import logging
import os
from typing import Optional
from urllib.parse import urlparse, urlunparse

import boto3

log = logging.getLogger("live_bridge.s3_presign")

_client = None


def _get_client():
    global _client
    if _client is None:
        kwargs = dict(
            aws_access_key_id=os.environ.get("S3_ACCESS_KEY", ""),
            aws_secret_access_key=os.environ.get("S3_SECRET_KEY", ""),
            region_name="us-east-1",
        )
        endpoint = os.environ.get("S3_ENDPOINT_URL", "")
        if endpoint:
            kwargs["endpoint_url"] = endpoint
        _client = boto3.client("s3", **kwargs)
    return _client


def _rewrite_to_public(url: str) -> str:
    """Replace the internal S3 endpoint host with the browser-accessible public host.

    Inside Docker the presigned URL carries minio:9000; browsers can't resolve
    that hostname. S3_PUBLIC_URL (e.g. http://localhost:9000) is the address
    the browser can actually reach.
    """
    public = os.environ.get("S3_PUBLIC_URL", "").rstrip("/")
    if not public or not url:
        return url
    parsed_url = urlparse(url)
    parsed_pub = urlparse(public)
    rewritten = parsed_url._replace(scheme=parsed_pub.scheme, netloc=parsed_pub.netloc)
    return urlunparse(rewritten)


def _presign_sync(s3_key: str, expiry_seconds: int) -> Optional[str]:
    bucket = os.environ.get("S3_BUCKET", "retailvision")
    try:
        url = _get_client().generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket, "Key": s3_key},
            ExpiresIn=expiry_seconds,
        )
        return _rewrite_to_public(url)
    except Exception as exc:
        log.warning("Presign failed key=%s: %s", s3_key, exc)
        return None


async def generate_presigned_url(s3_key: str, expiry_seconds: int = 30) -> Optional[str]:
    """Generate a presigned GET URL without blocking the event loop."""
    return await asyncio.to_thread(_presign_sync, s3_key, expiry_seconds)
