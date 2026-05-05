import boto3
from uuid import uuid4
import os

s3_client = boto3.client(
    "s3",
    aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
    aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
    region_name=os.getenv("AWS_REGION")
)

BUCKET_NAME = os.getenv("S3_BUCKET_NAME")


def upload_imagen(file_bytes: bytes, id_pieza: str, content_type: str = "image/jpeg") -> tuple[str, str]:
    """
    Sube imagen a S3 y retorna (bucket, key_s3)
    """
    key = f"piezas/{id_pieza}/{uuid4()}.jpg"

    s3_client.put_object(
        Bucket=BUCKET_NAME,
        Key=key,
        Body=file_bytes,
        ContentType=content_type
    )

    return BUCKET_NAME, key


def get_imagen_url(bucket: str, key_s3: str, expiration: int = 3600) -> str:
    """
    Genera URL temporal para ver la imagen (1 hora por default)
    """
    url = s3_client.generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket, "Key": key_s3},
        ExpiresIn=expiration
    )
    return url


def delete_imagen(bucket: str, key_s3: str) -> None:
    s3_client.delete_object(Bucket=bucket, Key=key_s3)