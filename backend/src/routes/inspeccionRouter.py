from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import case, desc, func
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


class ByResultBreakdown(BaseModel):
    correcto: int = 0
    anomalia: int = 0
    error: int = 0


class HourlyBucket(BaseModel):
    hour: str
    inspected: int
    rejected: int


class InspectionStats(BaseModel):
    total_inspections: int = 0
    by_result: ByResultBreakdown = ByResultBreakdown()
    fpy: float = 0.0
    rejection_rate: float = 0.0
    avg_processing_time: float = 0.0
    avg_similarity: float = 0.0
    hourly: list[HourlyBucket] = []
    recent: list[InspeccionSummary] = []


@router.get("/stats", response_model=InspectionStats)
async def stats(
    range: str = "all",
    session: AsyncSession = Depends(get_session),
):
    since: datetime | None = None
    now = datetime.now(timezone.utc)
    if range == "today":
        since = datetime.combine(now.date(), time.min, tzinfo=timezone.utc)
    elif range == "7d":
        since = now - timedelta(days=7)
    elif range == "30d":
        since = now - timedelta(days=30)

    # --- total + by_result + averages ---
    stmt = select(
        func.count(Inspeccion.id).label("total"),
        func.sum(case((Inspeccion.resultado_general == "correcto", 1), else_=0)).label("correcto"),
        func.sum(case((Inspeccion.resultado_general == "anomalia", 1), else_=0)).label("anomalia"),
        func.sum(case((Inspeccion.resultado_general == "error", 1), else_=0)).label("error"),
        func.avg(Inspeccion.tiempo_procesamiento).label("avg_time"),
        func.avg(Inspeccion.similitud).label("avg_sim"),
    )
    if since is not None:
        stmt = stmt.where(Inspeccion.fecha >= since)

    result = await session.exec(stmt)
    row = result.one()
    total = row.total or 0
    correcto = row.correcto or 0
    anomalia = row.anomalia or 0
    error = row.error or 0
    avg_time = round(float(row.avg_time or 0), 1)
    avg_sim = round(float(row.avg_sim or 0), 1)

    fpy = round(correcto / total * 100, 1) if total > 0 else 0.0
    rejection = round((anomalia + error) / total * 100, 1) if total > 0 else 0.0

    # --- hourly buckets ---
    hourly_stmt = (
        select(
            func.date_trunc("hour", Inspeccion.fecha).label("hour"),
            func.count(Inspeccion.id).label("inspected"),
            func.sum(
                case(
                    (Inspeccion.resultado_general.in_(["anomalia", "error"]), 1),
                    else_=0,
                )
            ).label("rejected"),
        )
        .group_by("hour")
        .order_by("hour")
        .limit(24)
    )
    if since is not None:
        hourly_stmt = hourly_stmt.where(Inspeccion.fecha >= since)

    hourly_result = await session.exec(hourly_stmt)
    hourly: list[HourlyBucket] = []
    for row_h in hourly_result.all():
        dt: datetime = row_h.hour
        hourly.append(HourlyBucket(
            hour=dt.strftime("%Hh"),
            inspected=row_h.inspected or 0,
            rejected=row_h.rejected or 0,
        ))

    # --- recent inspections ---
    recent_stmt = select(Inspeccion).order_by(desc(Inspeccion.fecha)).limit(10)
    if since is not None:
        recent_stmt = recent_stmt.where(Inspeccion.fecha >= since)

    recent_result = await session.exec(recent_stmt)
    recent_items = recent_result.all()

    return InspectionStats(
        total_inspections=total,
        by_result=ByResultBreakdown(
            correcto=correcto,
            anomalia=anomalia,
            error=error,
        ),
        fpy=fpy,
        rejection_rate=rejection,
        avg_processing_time=avg_time,
        avg_similarity=avg_sim,
        hourly=hourly,
        recent=[InspeccionSummary.model_validate(item) for item in recent_items],
    )


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
