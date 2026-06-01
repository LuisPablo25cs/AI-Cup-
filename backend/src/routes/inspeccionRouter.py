from __future__ import annotations

import asyncio
from datetime import date, datetime, time, timedelta, timezone
from typing import Literal, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import case, desc, func
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.db import get_session
from src.models.inspeccion import Deteccion, Inspeccion
from src.models.kit import Kit, KitPiezaLink
from src.models.pieza import Pieza
from src.models.vision_model import ModelPiezaLink, VisionModel
from src.services.detection import run_inference
from src.services.inference import get_or_load_model
from src.services.s3 import BUCKET_NAME, s3_client


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
    validado_por_operador: bool = False
    tipo_error: Optional[str] = None

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


class ValidateRequest(BaseModel):
    tipo_error: Literal["ninguno", "falso_positivo", "falso_negativo", "ambos"] = "ninguno"


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
    false_positive_rate: float = 0.0
    false_negative_rate: float = 0.0
    model_accuracy: float = 0.0
    operator_validation_rate: float = 0.0
    system_capacity: int = 0


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

    # --- validation KPIs (over validated inspections only) ---
    val_stmt = select(
        func.count(Inspeccion.id).label("total_validated"),
        func.sum(
            case((Inspeccion.tipo_error.in_(["falso_positivo", "ambos"]), 1), else_=0)
        ).label("false_positives"),
        func.sum(
            case((Inspeccion.tipo_error.in_(["falso_negativo", "ambos"]), 1), else_=0)
        ).label("false_negatives"),
        func.sum(
            case((Inspeccion.tipo_error == "ninguno", 1), else_=0)
        ).label("model_correct"),
    ).where(Inspeccion.validado_por_operador == True)
    if since is not None:
        val_stmt = val_stmt.where(Inspeccion.fecha >= since)

    val_result = await session.exec(val_stmt)
    val_row = val_result.one()
    total_validated = val_row.total_validated or 0
    false_positives = val_row.false_positives or 0
    false_negatives = val_row.false_negatives or 0
    model_correct = val_row.model_correct or 0

    false_positive_rate = round(false_positives / total_validated, 4) if total_validated > 0 else 0.0
    false_negative_rate = round(false_negatives / total_validated, 4) if total_validated > 0 else 0.0
    model_accuracy = round(model_correct / total_validated, 4) if total_validated > 0 else 0.0
    operator_validation_rate = round(total_validated / total, 4) if total > 0 else 0.0

    # --- system capacity: inspections in the last 60 minutes ---
    sixty_min_ago = now - timedelta(minutes=60)
    cap_stmt = select(func.count(Inspeccion.id)).where(Inspeccion.fecha >= sixty_min_ago)
    cap_result = await session.exec(cap_stmt)
    system_capacity = cap_result.one() or 0

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
        false_positive_rate=false_positive_rate,
        false_negative_rate=false_negative_rate,
        model_accuracy=model_accuracy,
        operator_validation_rate=operator_validation_rate,
        system_capacity=system_capacity,
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

    # Recalculate resultado_general based on corrected detections vs expected pieces.
    kp_stmt = select(KitPiezaLink).where(KitPiezaLink.kit_id == insp.kit_id)
    kp_result = await session.exec(kp_stmt)
    required_pieza_ids = {link.pieza_id for link in kp_result.all()}

    found_pieza_ids = {
        d.pieza_id
        for d in detecciones.values()
        if d.encontrado and d.pieza_id is not None
    }

    if required_pieza_ids and required_pieza_ids.issubset(found_pieza_ids):
        insp.resultado_general = "correcto"
    else:
        insp.resultado_general = "anomalia"
    session.add(insp)

    await session.commit()
    await session.refresh(insp, attribute_names=["detecciones"])
    return insp


@router.post("/{inspeccion_id}/validate", response_model=InspeccionRead)
async def validate_inspection(
    inspeccion_id: UUID,
    body: ValidateRequest,
    session: AsyncSession = Depends(get_session),
):
    insp = await session.get(Inspeccion, inspeccion_id)
    if not insp:
        raise HTTPException(status_code=404, detail="Inspection not found")

    insp.validado_por_operador = True
    insp.tipo_error = body.tipo_error
    session.add(insp)

    await session.commit()
    await session.refresh(insp, attribute_names=["detecciones"])
    return insp


@router.post("/", response_model=InspeccionRead, status_code=201)
async def create_inspection(
    kit_id: UUID = Form(...),
    image: UploadFile = File(...),
    operador: str | None = Form(None),
    session: AsyncSession = Depends(get_session),
) -> InspeccionRead:
    # --- 1. Validate image content type ---
    if image.content_type is None or not image.content_type.startswith("image/"):
        raise HTTPException(status_code=422, detail="image must be an image file")

    image_bytes = await image.read()

    # --- 2. Resolve Kit ---
    kit = await session.get(Kit, kit_id)
    if kit is None:
        raise HTTPException(status_code=404, detail="Kit not found")

    # --- 3. Guard: kit must have a vision_model_id ---
    if kit.vision_model_id is None:
        raise HTTPException(
            status_code=409,
            detail="No vision model associated with this kit",
        )

    # --- 4. Resolve VisionModel ---
    vision_model = await session.get(VisionModel, kit.vision_model_id)
    if vision_model is None:
        raise HTTPException(status_code=404, detail="Vision model not found")

    # --- 5. Guard: model must be COMPLETED ---
    if vision_model.estado != "COMPLETED":
        raise HTTPException(
            status_code=409,
            detail=f"Model not trained. Current status: {vision_model.estado}",
        )

    if vision_model.key_s3_weights is None:
        raise HTTPException(
            status_code=409,
            detail="Model weights not available (key_s3_weights is null)",
        )

    # --- 6. Load ModelPiezaLink → class_map ---
    mp_stmt = select(ModelPiezaLink).where(
        ModelPiezaLink.id_model == vision_model.id_model
    )
    mp_links = (await session.exec(mp_stmt)).all()

    if not mp_links:
        raise HTTPException(
            status_code=409,
            detail="No piece mappings found for this vision model",
        )

    # Fetch pieza names for the mapped pieces
    mp_pieza_ids = {link.id_pieza for link in mp_links}
    pieza_name_map: dict[UUID, str] = {}
    if mp_pieza_ids:
        p_stmt = select(Pieza).where(Pieza.id_pieza.in_(mp_pieza_ids))
        piezas = (await session.exec(p_stmt)).all()
        pieza_name_map = {p.id_pieza: p.nombre for p in piezas}

    class_map: dict[int, tuple[UUID, str]] = {}
    for link in mp_links:
        nombre = pieza_name_map.get(link.id_pieza, "Unknown")
        class_map[link.class_index] = (link.id_pieza, nombre)

    # --- 7. Load KitPiezaLink → expected pieces ---
    kp_stmt = select(KitPiezaLink).where(KitPiezaLink.kit_id == kit_id)
    kp_links = (await session.exec(kp_stmt)).all()

    kp_pieza_ids = {link.pieza_id for link in kp_links}
    kp_name_map: dict[UUID, str] = {}
    if kp_pieza_ids:
        kp_stmt2 = select(Pieza).where(Pieza.id_pieza.in_(kp_pieza_ids))
        kp_piezas = (await session.exec(kp_stmt2)).all()
        kp_name_map = {p.id_pieza: p.nombre for p in kp_piezas}

    expected_pieces: list[tuple[UUID, str, int]] = [
        (link.pieza_id, kp_name_map.get(link.pieza_id, "Unknown"), link.cantidad_requerida)
        for link in kp_links
    ]

    # --- 8. Get or load cached YOLO model ---
    try:
        model = await get_or_load_model(
            vision_model.id_model, vision_model.key_s3_weights
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to load inference model: {exc}",
        )

    # --- 9. Run inference (offloaded to thread) ---
    try:
        inference_result = await asyncio.to_thread(
            run_inference,
            image_bytes,
            model,
            class_map,
            expected_pieces,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Inference failed: {exc}",
        )

    # --- 10. Create Inspeccion row ---
    inspeccion = Inspeccion(
        kit_id=kit_id,
        vision_model_id=vision_model.id_model,
        kit_nombre=kit.nombre,
        resultado_general=inference_result.resultado_general,
        similitud=inference_result.similitud,
        tiempo_procesamiento=inference_result.tiempo_procesamiento,
        operador=operador,
    )
    session.add(inspeccion)

    # --- 11. Bulk-insert Deteccion rows ---
    for det in inference_result.detections:
        deteccion = Deteccion(
            inspeccion=inspeccion,
            pieza_id=det.pieza_id,
            pieza_nombre=det.pieza_nombre,
            encontrado=det.encontrado,
            confianza=det.confianza,
            posicion_x_pct=det.bbox[0] if det.bbox else None,
            posicion_y_pct=det.bbox[1] if det.bbox else None,
            width_pct=det.bbox[2] if det.bbox else None,
            height_pct=det.bbox[3] if det.bbox else None,
            estado="correcto" if det.encontrado else "faltante",
        )
        session.add(deteccion)

    # Flush to obtain inspeccion.id for the S3 key (transaction not committed yet)
    await session.flush()

    # --- 12. Upload original image to S3 ---
    s3_key = f"inspections/{inspeccion.id}/original.jpg"
    try:
        s3_client.put_object(
            Bucket=BUCKET_NAME,
            Key=s3_key,
            Body=image_bytes,
            ContentType=image.content_type or "image/jpeg",
        )
    except Exception as exc:
        await session.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Failed to upload image to S3: {exc}",
        )

    # --- 13. Persist S3 key ---
    inspeccion.imagen_s3_key = s3_key

    # --- 14. Commit transaction ---
    await session.commit()
    await session.refresh(inspeccion, attribute_names=["detecciones"])

    # --- 15. Return response ---
    return inspeccion
