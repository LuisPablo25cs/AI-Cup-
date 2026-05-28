import boto3
import shutil
from botocore.config import Config as BotoConfig
from pathlib import Path
from ..config.config import config

class S3Client:
    def __init__(self):
        # Support fallback to EC2 instance profile / local credentials if env variables are omitted
        s3_kwargs = {
            "region_name": config.AWS_REGION,
            "config": BotoConfig(signature_version="s3v4")
        }
        if config.AWS_ACCESS_KEY_ID:
            s3_kwargs["aws_access_key_id"] = config.AWS_ACCESS_KEY_ID
        if config.AWS_SECRET_ACCESS_KEY:
            s3_kwargs["aws_secret_access_key"] = config.AWS_SECRET_ACCESS_KEY

        self.s3 = boto3.client("s3", **s3_kwargs)
        self.bucket = config.S3_BUCKET_NAME

    def download_file(self, s3_key: str, local_path: Path) -> None:
        """Downloads a file from S3 to a local workspace path."""
        local_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.s3.download_file(self.bucket, s3_key, str(local_path))
        except Exception as e:
            raise IOError(f"Failed to download S3 key '{s3_key}' from bucket '{self.bucket}': {e}")

    def download_file_cached(self, s3_key: str, local_path: Path) -> None:
        """Downloads from S3 with a local disk cache.

        On first request, downloads from S3 and saves a copy to the cache directory.
        Subsequent requests copy from the cache without touching S3.
        Cache is append-only — the user cleans it manually.
        """
        cache_path = config.S3_CACHE_DIR / s3_key

        if cache_path.exists():
            local_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(cache_path, local_path)
            return

        cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.download_file(s3_key, cache_path)
        shutil.copy2(cache_path, local_path)

    def upload_file(self, local_path: Path, s3_key: str) -> None:
        """Uploads a local file to the configured S3 bucket."""
        if not local_path.exists():
            raise FileNotFoundError(f"Local file '{local_path}' does not exist for upload.")
        try:
            self.s3.upload_file(str(local_path), self.bucket, s3_key)
        except Exception as e:
            raise IOError(f"Failed to upload '{local_path}' to S3 key '{s3_key}' in bucket '{self.bucket}': {e}")