from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from pydantic import BaseModel, Field as PydField, model_validator
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession
from uuid import UUID
from datetime import datetime

from src.db import get_session
from src.dependencies.admin_key import require_admin_key
from src.models.kit import Kit, KitPiezaLink
from src.models.inspeccion import Inspeccion
from src.models.pieza import Pieza
from src.models.vision_model import VisionModel

logger = logging.getLogger(__name__)


router = APIRouter(prefix="/api/kits", tags=["Kits"])


class KitItemCreate(BaseModel):
    pieza_id: UUID
    cantidad_requerida: int = PydField(default=1, gt=0)
    pos_x: float | None = None
    pos_y: float | None = None
    ancho_cm: float | None = None
    alto_cm: float | None = None
    icono: str | None = None
    es_agrupacion: bool = False


class KitItemUpdate(BaseModel):
    cantidad_requerida: int | None = PydField(default=None, gt=0)
    pos_x: float | None = None
    pos_y: float | None = None
    ancho_cm: float | None = None
    alto_cm: float | None = None
    icono: str | None = None
    es_agrupacion: bool | None = None


class KitCreate(BaseModel):
    nombre: str
    descripcion: str | None = None
    activo: bool = True
    ancho_cm: float | None = None
    largo_cm: float | None = None
    imagen_url: str | None = None
    vision_model_id: UUID | None = None


class KitUpdate(BaseModel):
    nombre: str | None = None
    descripcion: str | None = None
    activo: bool | None = None
    ancho_cm: float | None = None
    largo_cm: float | None = None
    imagen_url: str | None = None
    vision_model_id: UUID | None = None


class KitItemRead(BaseModel):
    id: UUID
    kit_id: UUID
    pieza_id: UUID
    cantidad_requerida: int
    pos_x: float | None
    pos_y: float | None
    ancho_cm: float | None
    alto_cm: float | None
    icono: str | None
    es_agrupacion: bool

    model_config = {"from_attributes": True}


class KitRead(BaseModel):
    id: UUID
    nombre: str
    descripcion: str | None
    activo: bool
    ancho_cm: float | None
    largo_cm: float | None
    imagen_url: str | None
    vision_model_id: UUID | None
    created_at: datetime
    items: list[KitItemRead] = []

    model_config = {"from_attributes": True}

    @model_validator(mode='after')
    def resolve_imagen_url(self) -> 'KitRead':
        if self.imagen_url and not self.imagen_url.startswith('http'):
            from src.services.s3 import get_object_read_url, BUCKET_NAME
            self.imagen_url = get_object_read_url(BUCKET_NAME, self.imagen_url)
        return self


@router.post("/", response_model=KitRead, status_code=201)
async def create_kit(
    data: KitCreate,
    session: AsyncSession = Depends(get_session),
):
    if data.vision_model_id:
        vm = await session.get(VisionModel, data.vision_model_id)
        if not vm:
            raise HTTPException(status_code=404, detail="VisionModel not found")

    kit = Kit(**data.model_dump())
    session.add(kit)
    await session.commit()
    await session.refresh(kit)
    return kit


@router.get("/", response_model=list[KitRead])
async def list_kits(
    session: AsyncSession = Depends(get_session),
):
    result = await session.exec(select(Kit))
    kits = result.all()
    # List view does not include item details.
    return [KitRead.model_validate({**k.model_dump(), "items": []}) for k in kits]


@router.get("/{kit_id}", response_model=KitRead)
async def get_kit(
    kit_id: UUID,
    session: AsyncSession = Depends(get_session),
):
    kit = await session.get(Kit, kit_id)
    if not kit:
        raise HTTPException(status_code=404, detail="Kit not found")
    await session.refresh(kit, attribute_names=["items"])
    return kit


@router.put("/{kit_id}", response_model=KitRead)
async def update_kit(
    kit_id: UUID,
    data: KitUpdate,
    session: AsyncSession = Depends(get_session),
):
    kit = await session.get(Kit, kit_id)
    if not kit:
        raise HTTPException(status_code=404, detail="Kit not found")

    payload = data.model_dump(exclude_unset=True)
    if "vision_model_id" in payload and payload["vision_model_id"] is not None:
        vm = await session.get(VisionModel, payload["vision_model_id"])
        if not vm:
            raise HTTPException(status_code=404, detail="VisionModel not found")

    for k, v in payload.items():
        setattr(kit, k, v)

    session.add(kit)
    await session.commit()
    await session.refresh(kit)
    await session.refresh(kit, attribute_names=["items"])
    return kit


@router.delete("/{kit_id}", status_code=204)
async def delete_kit(
    kit_id: UUID,
    session: AsyncSession = Depends(get_session),
    _admin: str = Depends(require_admin_key),
):
    from src.services.s3 import delete_object, BUCKET_NAME

    kit = await session.get(Kit, kit_id)
    if not kit:
        raise HTTPException(status_code=404, detail="Kit not found")

    s3_key = kit.imagen_url  # capture before delete

    # Null out Inspeccion.kit_id for all inspections linked to this kit.
    # Preserves audit trail via kit_nombre snapshot.
    insp_result = await session.exec(
        select(Inspeccion).where(Inspeccion.kit_id == kit_id)
    )
    for insp in insp_result.all():
        insp.kit_id = None
        session.add(insp)

    # KitPiezaLink rows cascade via "all, delete-orphan" on Kit.items
    # and ondelete="CASCADE" FK. Explicit delete is safe.
    link_result = await session.exec(
        select(KitPiezaLink).where(KitPiezaLink.kit_id == kit_id)
    )
    for link in link_result.all():
        await session.delete(link)

    await session.delete(kit)
    await session.commit()

    # S3 cleanup AFTER commit (best-effort — never roll back a valid DB tx)
    if s3_key:
        try:
            delete_object(BUCKET_NAME, s3_key)
        except Exception:
            logger.warning(
                "Failed to delete S3 cover for kit %s: %s", kit_id, s3_key
            )


ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}
MAX_IMAGE_SIZE = 5 * 1024 * 1024


@router.post("/{kit_id}/image", response_model=KitRead)
async def upload_kit_image(
    kit_id: UUID,
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
):
    from src.services.s3 import upload_kit_image as s3_upload_kit_image

    if file.content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type. Allowed: {', '.join(ALLOWED_IMAGE_TYPES)}",
        )

    file_bytes = await file.read()
    if len(file_bytes) > MAX_IMAGE_SIZE:
        raise HTTPException(status_code=400, detail="File exceeds the 5 MB size limit")

    kit = await session.get(Kit, kit_id)
    if not kit:
        raise HTTPException(status_code=404, detail="Kit not found")

    s3_key = f"kits/{kit_id}/cover.jpg"
    s3_upload_kit_image(file_bytes, s3_key, file.content_type)

    kit.imagen_url = s3_key
    session.add(kit)
    await session.commit()
    await session.refresh(kit)
    await session.refresh(kit, attribute_names=["items"])

    return KitRead.model_validate(kit)


@router.post("/{kit_id}/items", response_model=KitItemRead, status_code=201)
async def add_item(
    kit_id: UUID,
    data: KitItemCreate,
    session: AsyncSession = Depends(get_session),
):
    kit = await session.get(Kit, kit_id)
    if not kit:
        raise HTTPException(status_code=404, detail="Kit not found")

    pieza = await session.get(Pieza, data.pieza_id)
    if not pieza:
        raise HTTPException(status_code=404, detail="Pieza not found")

    existing = await session.exec(
        select(KitPiezaLink).where(
            KitPiezaLink.kit_id == kit_id,
            KitPiezaLink.pieza_id == data.pieza_id,
        )
    )
    if existing.first():
        raise HTTPException(status_code=409, detail="Pieza already linked to kit")

    item = KitPiezaLink(kit_id=kit_id, **data.model_dump())
    session.add(item)
    await session.commit()
    await session.refresh(item)
    return item


@router.put("/{kit_id}/items/{item_id}", response_model=KitItemRead)
async def update_item(
    kit_id: UUID,
    item_id: UUID,
    data: KitItemUpdate,
    session: AsyncSession = Depends(get_session),
):
    result = await session.exec(
        select(KitPiezaLink).where(
            KitPiezaLink.id == item_id,
            KitPiezaLink.kit_id == kit_id,
        )
    )
    item = result.first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    payload = data.model_dump(exclude_unset=True)
    for k, v in payload.items():
        setattr(item, k, v)

    session.add(item)
    await session.commit()
    await session.refresh(item)
    return item


@router.delete("/{kit_id}/items/{item_id}", status_code=204)
async def delete_item(
    kit_id: UUID,
    item_id: UUID,
    session: AsyncSession = Depends(get_session),
):
    result = await session.exec(
        select(KitPiezaLink).where(
            KitPiezaLink.id == item_id,
            KitPiezaLink.kit_id == kit_id,
        )
    )
    item = result.first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    await session.delete(item)
    await session.commit()
