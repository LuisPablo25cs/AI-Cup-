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


def upload_label(file_bytes: bytes, id_pieza: str, filename_uuid: str, variante: str = "sin_bolsa") -> tuple[str, str]:
    """
    Sube archivo de etiquetas (.txt) a S3 en la carpeta de su variante y retorna (bucket, key_s3_label)
    """
    key = f"piezas/{id_pieza}/{variante}/{filename_uuid}.txt"  # <-- Ahora usa la variante y coincide con la imagen

    s3_client.put_object(
        Bucket=BUCKET_NAME,
        Key=key,
        Body=file_bytes,
        ContentType="text/plain"
    )

    return BUCKET_NAME, key

def upload_label(file_bytes: bytes, id_pieza: str, filename_uuid: str) -> tuple[str, str]:
    """
    Sube archivo de etiquetas (.txt) a S3 y retorna (bucket, key_s3_label)
    """
    key = f"piezas/{id_pieza}/{filename_uuid}.txt"

    s3_client.put_object(
        Bucket=BUCKET_NAME,
        Key=key,
        Body=file_bytes,
        ContentType="text/plain"
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