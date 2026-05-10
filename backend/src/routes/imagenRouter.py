from fastapi import APIRouter, UploadFile, File, Depends, HTTPException
from sqlmodel.ext.asyncio.session import AsyncSession
from src.db import get_session
from src.models.imagen import Imagen
from src.models.pieza import Pieza
from src.services.s3 import upload_imagen
from uuid import UUID

router = APIRouter(prefix="/imagenes", tags=["Imagenes"])


@router.post("/{id_pieza}")
async def subir_imagen(
    id_pieza: UUID,
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session)
):
    # Validar que la pieza existe ANTES de tocar S3
    pieza = await session.get(Pieza, id_pieza)
    if not pieza:
        raise HTTPException(status_code=404, detail="Pieza no encontrada")

    if not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="El archivo debe ser una imagen")

    file_bytes = await file.read()
    bucket, key_s3 = upload_imagen(file_bytes, str(id_pieza), file.content_type)

    imagen = Imagen(id_pieza=id_pieza, bucket=bucket, key_s3=key_s3)
    session.add(imagen)
    await session.commit()
    await session.refresh(imagen)

    return {"id_imagen": imagen.id_imagen, "key_s3": imagen.key_s3}