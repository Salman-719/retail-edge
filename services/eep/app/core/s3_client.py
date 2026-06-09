import boto3
from botocore.exceptions import ClientError
from app.core.config import settings
from app.core.resilience import s3_config


def _client():
    return boto3.client(
        "s3",
        endpoint_url=settings.S3_ENDPOINT_URL,
        aws_access_key_id=settings.S3_ACCESS_KEY,
        aws_secret_access_key=settings.S3_SECRET_KEY,
        config=s3_config(),
    )


def _public_client():
    """Client using the browser-accessible public URL for presigned URL generation."""
    public_url = settings.S3_PUBLIC_URL or settings.S3_ENDPOINT_URL
    return boto3.client(
        "s3",
        endpoint_url=public_url,
        aws_access_key_id=settings.S3_ACCESS_KEY,
        aws_secret_access_key=settings.S3_SECRET_KEY,
        config=s3_config(),
    )


def ensure_bucket() -> None:
    client = _client()
    try:
        client.head_bucket(Bucket=settings.S3_BUCKET)
    except ClientError:
        client.create_bucket(Bucket=settings.S3_BUCKET)

    # Allow browsers to load presigned URLs directly. MinIO does not implement
    # PutBucketCors and returns NotImplemented — expected and harmless.
    try:
        client.put_bucket_cors(
            Bucket=settings.S3_BUCKET,
            CORSConfiguration={
                "CORSRules": [{
                    "AllowedHeaders": ["*"],
                    "AllowedMethods": ["GET"],
                    "AllowedOrigins": ["*"],
                    "MaxAgeSeconds": 3600,
                }]
            },
        )
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "NotImplemented":
            raise


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


def generate_presigned_url_public(s3_key: str, expiry: int = 3600) -> str:
    """Generate a presigned URL via the public endpoint so browsers can fetch it directly."""
    return _public_client().generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.S3_BUCKET, "Key": s3_key},
        ExpiresIn=expiry,
    )


def delete_object(s3_key: str) -> None:
    _client().delete_object(Bucket=settings.S3_BUCKET, Key=s3_key)


def copy_object(source_key: str, dest_key: str) -> None:
    _client().copy_object(
        Bucket=settings.S3_BUCKET,
        CopySource={"Bucket": settings.S3_BUCKET, "Key": source_key},
        Key=dest_key,
    )
