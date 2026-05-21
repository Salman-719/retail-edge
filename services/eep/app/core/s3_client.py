import boto3
from botocore.exceptions import ClientError
from app.core.config import settings


def _client():
    return boto3.client(
        "s3",
        endpoint_url=settings.S3_ENDPOINT_URL,
        aws_access_key_id=settings.S3_ACCESS_KEY,
        aws_secret_access_key=settings.S3_SECRET_KEY,
    )


def ensure_bucket() -> None:
    client = _client()
    try:
        client.head_bucket(Bucket=settings.S3_BUCKET)
    except ClientError:
        client.create_bucket(Bucket=settings.S3_BUCKET)


def upload_bytes(data: bytes, s3_key: str, content_type: str = "application/octet-stream") -> None:
    _client().put_object(
        Bucket=settings.S3_BUCKET,
        Key=s3_key,
        Body=data,
        ContentType=content_type,
    )


def generate_presigned_url(s3_key: str, expiry: int = 3600) -> str:
    return _client().generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.S3_BUCKET, "Key": s3_key},
        ExpiresIn=expiry,
    )


def delete_object(s3_key: str) -> None:
    _client().delete_object(Bucket=settings.S3_BUCKET, Key=s3_key)
