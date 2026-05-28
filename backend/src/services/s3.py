import boto3
import os
from uuid import UUID
from botocore.config import Config
from src.models.imagen import BagVariant

AWS_REGION = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "us-east-2"

s3_client = boto3.client(
    "s3",
    aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
    aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
    region_name=AWS_REGION,
    endpoint_url=f"https://s3.{AWS_REGION}.amazonaws.com",
    config=Config(signature_version="s3v4", s3={"addressing_style": "virtual"}),
)

BUCKET_NAME = os.getenv("S3_BUCKET_NAME")

#Upload

"""
    Sube imagen a S3 y retorna (bucket, key_s3)
    S3 path: piezas/{id_pieza}/{frame_set}/{variante}.jpg
"""

def upload_imagen(
        file_bytes: bytes,
        id_pieza: str,
        frame_name: str, #(fondo_perfil_vista)
        variante: BagVariant, 
        content_type: str = "image/jpeg") -> tuple[str, str]:

    #TO DO: capaz que el nombre no sea variante si no un uuid
    key = f"piezas/{id_pieza}/{frame_name}/{variante}.jpg"

    s3_client.put_object(
        Bucket=BUCKET_NAME,
        Key=key,
        Body=file_bytes,
        ContentType=content_type
    )

    return BUCKET_NAME, key



"""
    Sube archivo de etiquetas (.txt) a S3 en la carpeta de su render_set
    y retorna (bucket, key_s3_label)
    S3 path: piezas/{id_pieza}/{id_render_set}/label.txt
"""

def upload_label(
        file_bytes: bytes,
        id_pieza: str,
        id_render_set: str,
        content_type:str = "text/plain",
        ) -> tuple[str, str]:

    key = f"piezas/{id_pieza}/{id_render_set}/label.txt" 

    s3_client.put_object(
        Bucket=BUCKET_NAME,
        Key=key,
        Body=file_bytes,
        ContentType=content_type
    )

    return BUCKET_NAME, key


"""
    Sube modelo de vision ed YOLO a S3 y retorna (bucket, key_s3)
    S3 path: models/{uuid}.pt
"""

def upload_model(
        file_bytes: bytes,
        id_model: UUID,
        content_type: str = "model/pt") -> tuple[str, str]:

    #TO DO: capaz que el nombre no sea variante si no un uuid
    key = f"model/{id_model}.pt"

    s3_client.put_object(
        Bucket=BUCKET_NAME,
        Key=key,
        Body=file_bytes,
        ContentType=content_type
    )

    return BUCKET_NAME, key

#Other operations

def get_object_read_url(bucket: str, key_s3: str, expiration: int = 3600) -> str:
    """
    Genera URL temporal para ver un objeto (1 hora por default)
    """
    url = s3_client.generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket, "Key": key_s3},
        ExpiresIn=expiration
    )
    return url


def delete_object(bucket: str, key_s3: str) -> None:
    s3_client.delete_object(Bucket=bucket, Key=key_s3)
