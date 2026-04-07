import io
import boto3
from botocore.exceptions import ClientError
import logging

from app.core.config import settings

logger = logging.getLogger(__name__)


class S3Client:
    def __init__(self):
        self._client = None

    def _get_client(self):
        if self._client is None:
            self._client = boto3.client(
                "s3",
                endpoint_url=settings.S3_ENDPOINT_URL,
                aws_access_key_id=settings.S3_ACCESS_KEY,
                aws_secret_access_key=settings.S3_SECRET_KEY,
                region_name="us-east-1",
            )
        return self._client

    def ensure_bucket(self):
        client = self._get_client()
        try:
            client.head_bucket(Bucket=settings.S3_BUCKET)
            logger.info(f"S3 bucket '{settings.S3_BUCKET}' already exists")
        except ClientError as e:
            if e.response["Error"]["Code"] in ("404", "NoSuchBucket"):
                client.create_bucket(Bucket=settings.S3_BUCKET)
                logger.info(f"Created S3 bucket '{settings.S3_BUCKET}'")
            else:
                raise

    def upload_bytes(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        client = self._get_client()
        client.put_object(
            Bucket=settings.S3_BUCKET,
            Key=key,
            Body=data,
            ContentType=content_type,
        )
        return key

    def upload_file(self, key: str, file_path: str, content_type: str = "application/octet-stream") -> str:
        client = self._get_client()
        client.upload_file(
            Filename=file_path,
            Bucket=settings.S3_BUCKET,
            Key=key,
            ExtraArgs={"ContentType": content_type},
        )
        return key

    def download_bytes(self, key: str) -> bytes:
        client = self._get_client()
        response = client.get_object(Bucket=settings.S3_BUCKET, Key=key)
        return response["Body"].read()

    def download_to_file(self, key: str, dest_path: str):
        client = self._get_client()
        client.download_file(Bucket=settings.S3_BUCKET, Key=key, Filename=dest_path)

    def get_presigned_url(self, key: str, expires_in: int = 3600) -> str:
        client = self._get_client()
        return client.generate_presigned_url(
            "get_object",
            Params={"Bucket": settings.S3_BUCKET, "Key": key},
            ExpiresIn=expires_in,
        )

    def delete(self, key: str):
        client = self._get_client()
        client.delete_object(Bucket=settings.S3_BUCKET, Key=key)

    def key_exists(self, key: str) -> bool:
        client = self._get_client()
        try:
            client.head_object(Bucket=settings.S3_BUCKET, Key=key)
            return True
        except ClientError:
            return False


s3_client = S3Client()
