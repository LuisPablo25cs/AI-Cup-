import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import select
from src.db import get_session
from src.dependencies.admin_key import require_admin_key
from src.models.pieza import Pieza
from src.models.kit import Kit, KitPiezaLink
from src.models.vision_model import VisionModel, ModelPiezaLink
from src.models.render_set import RenderSet
from src.models.imagen import Imagen
from src.services.s3 import get_object_read_url
from uuid import UUID
from datetime import datetime, timezone
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/piezas", tags=["Piezas"])


# ── Schemas ────────────────────────────────────────────────────────────────────

class PiezaCreate(BaseModel):
    nombre: str
    descripcion: str | None = None
    cantidad_estimada: int = 1


class PiezaUpdate(BaseModel):
    nombre: str | None = None
    descripcion: str | None = None
    cantidad_estimada: int | None = None
    activo: bool | None = None


class ThumbnailsRequest(BaseModel):
    piezas: list[UUID]


class ThumbnailEntry(BaseModel):
    id_pieza: UUID
    url: str | None


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.post("/", response_model=Pieza)
async def crear_pieza(
    data: PiezaCreate,
    session: AsyncSession = Depends(get_session)
):
    pieza = Pieza(**data.model_dump())
    session.add(pieza)
    await session.commit()
    await session.refresh(pieza)
    return pieza


@router.get("/", response_model=list[Pieza])
async def obtener_piezas(
    session: AsyncSession = Depends(get_session)
):
    result = await session.exec(select(Pieza))
    return result.all()


@router.post("/thumbnails", response_model=list[ThumbnailEntry])
async def obtener_thumbnails(
    data: ThumbnailsRequest,
    session: AsyncSession = Depends(get_session),
):
    """Return a presigned URL for one sample image per requested pieza.

    Looks up the first `Imagen` linked through `RenderSet` for each pieza.
    Returns `null` URL when the pieza has no images yet.
    """
    if not data.piezas:
        return []

    result = await session.exec(
        select(Imagen, RenderSet.id_pieza)
        .join(RenderSet, Imagen.id_render_set == RenderSet.id_render_set)
        .where(RenderSet.id_pieza.in_(data.piezas))
    )

    first_per_pieza: dict[UUID, Imagen] = {}
    for imagen, id_pieza in result.all():
        if id_pieza not in first_per_pieza:
            first_per_pieza[id_pieza] = imagen

    entries: list[ThumbnailEntry] = []
    for id_pieza in data.piezas:
        imagen = first_per_pieza.get(id_pieza)
        url = (
            get_object_read_url(imagen.bucket, imagen.key_s3)
            if imagen and imagen.bucket and imagen.key_s3
            else None
        )
        entries.append(ThumbnailEntry(id_pieza=id_pieza, url=url))

    return entries


@router.get("/{id_pieza}", response_model=Pieza)
async def obtener_pieza(
    id_pieza: UUID,
    session: AsyncSession = Depends(get_session)
):
    pieza = await session.get(Pieza, id_pieza)
    if not pieza:
        raise HTTPException(status_code=404, detail="Pieza no encontrada")
    return pieza


@router.patch("/{id_pieza}", response_model=Pieza)
async def actualizar_pieza(
    id_pieza: UUID,
    data: PiezaUpdate,
    session: AsyncSession = Depends(get_session)
):
    pieza = await session.get(Pieza, id_pieza)
    if not pieza:
        raise HTTPException(status_code=404, detail="Pieza no encontrada")

    campos = data.model_dump(exclude_unset=True)  # solo campos enviados
    for campo, valor in campos.items():
        setattr(pieza, campo, valor)

    pieza.edited_at = datetime.now(timezone.utc)
    session.add(pieza)
    await session.commit()
    await session.refresh(pieza)
    return pieza


@router.delete("/{id_pieza}", status_code=204)
async def eliminar_pieza(
    id_pieza: UUID,
    session: AsyncSession = Depends(get_session),
    _admin: str = Depends(require_admin_key),
):
    from src.services.s3 import delete_prefix, BUCKET_NAME

    pieza = await session.get(Pieza, id_pieza)
    if not pieza:
        raise HTTPException(status_code=404, detail="Pieza no encontrada")

    # Pre-flight: check references from kits and models
    kit_refs_result = await session.exec(
        select(KitPiezaLink, Kit.nombre)
        .join(Kit, Kit.id == KitPiezaLink.kit_id)
        .where(KitPiezaLink.pieza_id == id_pieza)
    )
    kit_refs = kit_refs_result.all()

    model_refs_result = await session.exec(
        select(ModelPiezaLink, VisionModel.nombre)
        .join(VisionModel, VisionModel.id_model == ModelPiezaLink.id_model)
        .where(ModelPiezaLink.id_pieza == id_pieza)
    )
    model_refs = model_refs_result.all()

    if kit_refs or model_refs:
        entities = []
        for _link, kit_name in kit_refs:
            entities.append({"type": "kit", "name": kit_name})
        for _link, model_name in model_refs:
            entities.append({"type": "model", "name": model_name})

        count = len(entities)
        raise HTTPException(
            status_code=409,
            detail={
                "message": f"Pieza referenced by {count} entity(s)",
                "entities": entities,
            },
        )

    await session.delete(pieza)
    await session.commit()

    # S3 cleanup AFTER commit (best-effort)
    try:
        delete_prefix(BUCKET_NAME, f"piezas/{id_pieza}/")
    except Exception:
        logger.warning(
            "Failed to delete S3 prefix for pieza %s", id_pieza
        )