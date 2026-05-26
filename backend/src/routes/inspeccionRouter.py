from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import desc
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.db import get_session
from src.models.inspeccion import Deteccion, Inspeccion


router = APIRouter(prefix="/api/inspections", tags=["Inspections"])


class DeteccionRead(BaseModel):
    id: UUID
    inspeccion_id: UUID
    pieza_id: UUID | None
    pieza_nombre: str
    encontrado: bool
    confianza: float
    posicion_x_pct: float | None
    posicion_y_pct: float | None
    width_pct: float | None
    height_pct: float | None
    estado: str | None
    corregido_por_operador: bool

    model_config = {"from_attributes": True}


class InspeccionSummary(BaseModel):
    id: UUID
    kit_id: UUID
    kit_nombre: str
    fecha: datetime
    resultado_general: str
    similitud: float
    tiempo_procesamiento: float
    operador: str | None
    imagen_s3_key: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class InspeccionRead(InspeccionSummary):
    detecciones: list[DeteccionRead] = []


class InspeccionResultRead(BaseModel):
    id_inspeccion: UUID
    similitud: float
    resultado_general: str
    tiempo_procesamiento: float
    detecciones: list[DeteccionRead]


class DeteccionCorrection(BaseModel):
    deteccion_id: UUID
    encontrado: bool
    estado: str | None = None


class ConfirmRequest(BaseModel):
    corrections: list[DeteccionCorrection]


@router.get("/", response_model=list[InspeccionSummary])
async def list_inspections(
    kit_id: UUID | None = None,
    resultado_general: str | None = None,
    fecha_desde: date | None = None,
    fecha_hasta: date | None = None,
    operador: str | None = None,
    session: AsyncSession = Depends(get_session),
):
    query = select(Inspeccion)

    if kit_id is not None:
        query = query.where(Inspeccion.kit_id == kit_id)
    if resultado_general is not None:
        query = query.where(Inspeccion.resultado_general == resultado_general)
    if fecha_desde is not None:
        start_dt = datetime.combine(fecha_desde, time.min, tzinfo=timezone.utc)
        query = query.where(Inspeccion.fecha >= start_dt)
    if fecha_hasta is not None:
        # Inclusive end date.
        end_dt = datetime.combine(
            fecha_hasta + timedelta(days=1),
            time.min,
            tzinfo=timezone.utc,
        )
        query = query.where(Inspeccion.fecha < end_dt)
    if operador:
        query = query.where(Inspeccion.operador.ilike(f"%{operador}%"))

    query = query.order_by(desc(Inspeccion.fecha))
    result = await session.exec(query)
    return result.all()


@router.get("/{inspeccion_id}", response_model=InspeccionRead)
async def get_inspection(
    inspeccion_id: UUID,
    session: AsyncSession = Depends(get_session),
):
    insp = await session.get(Inspeccion, inspeccion_id)
    if not insp:
        raise HTTPException(status_code=404, detail="Inspection not found")
    await session.refresh(insp, attribute_names=["detecciones"])
    return insp


@router.get("/{inspeccion_id}/result", response_model=InspeccionResultRead)
async def get_result(
    inspeccion_id: UUID,
    session: AsyncSession = Depends(get_session),
):
    insp = await session.get(Inspeccion, inspeccion_id)
    if not insp:
        raise HTTPException(status_code=404, detail="Inspection not found")
    await session.refresh(insp, attribute_names=["detecciones"])

    return InspeccionResultRead(
        id_inspeccion=insp.id,
        similitud=insp.similitud,
        resultado_general=insp.resultado_general,
        tiempo_procesamiento=insp.tiempo_procesamiento,
        detecciones=[DeteccionRead.model_validate(d) for d in (insp.detecciones or [])],
    )


@router.post("/{inspeccion_id}/confirm", response_model=InspeccionRead)
async def confirm(
    inspeccion_id: UUID,
    body: ConfirmRequest,
    session: AsyncSession = Depends(get_session),
):
    insp = await session.get(Inspeccion, inspeccion_id)
    if not insp:
        raise HTTPException(status_code=404, detail="Inspection not found")

    # Load all detections once so we can validate ownership and update in-memory.
    result = await session.exec(select(Deteccion).where(Deteccion.inspeccion_id == inspeccion_id))
    detecciones = {d.id: d for d in result.all()}

    for c in body.corrections:
        d = detecciones.get(c.deteccion_id)
        if not d:
            raise HTTPException(
                status_code=422,
                detail=f"deteccion_id does not belong to inspection: {c.deteccion_id}",
            )
        d.encontrado = c.encontrado
        d.estado = c.estado
        d.corregido_por_operador = True
        session.add(d)

    await session.commit()
    await session.refresh(insp, attribute_names=["detecciones"])
    return insp
