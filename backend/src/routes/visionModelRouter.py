from fastapi import APIRouter, File, UploadFile, HTTPException
from typing import List, Optional
from datetime import datetime
import os
import aio_pika
import json
import uuid
import io
from PIL import Image
from sqlmodel import select
from sqlalchemy import func

from src.db import AsyncSessionLocal
from src.models.pieza import Pieza
from src.models.vision_model import VisionModel, ModelPiezaLink
from pydantic import BaseModel

class GenerateModelRequest(BaseModel):
    nombre: str
    piezas: List[uuid.UUID]


class ModelPiezaEntry(BaseModel):
    id_pieza: uuid.UUID
    nombre: Optional[str] = None
    class_index: Optional[int] = None


class VisionModelListEntry(BaseModel):
    id_model: uuid.UUID
    nombre: str
    estado: str
    created_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    piezas_count: int = 0
    key_s3_weights: Optional[str] = None


class VisionModelDetail(VisionModelListEntry):
    piezas: List[ModelPiezaEntry] = []


router = APIRouter(tags=["Vision Models"])

RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "rabbitmq")

@router.post("/generateModel")
async def generateModel(request: GenerateModelRequest):
    if not request.nombre.strip():
        raise HTTPException(status_code=400, detail="Model name cannot be empty")
    if not request.piezas:
        raise HTTPException(status_code=400, detail="Must provide at least one piece ID for training")
        
    # 1. Verify that all piece IDs exist in the database
    async with AsyncSessionLocal() as db_session:
        for idx, p_id in enumerate(request.piezas):
            pieza = await db_session.get(Pieza, p_id)
            if not pieza:
                raise HTTPException(status_code=404, detail=f"Piece with ID {p_id} not found")

        # 2. Create the VisionModel entry in Postgres
        model = VisionModel(nombre=request.nombre, estado="QUEUED")
        db_session.add(model)
        await db_session.commit()
        await db_session.refresh(model)

        # 3. Create the ModelPiezaLink entries linking each piece to this model
        for idx, p_id in enumerate(request.piezas):
            link = ModelPiezaLink(id_model=model.id_model, id_pieza=p_id, class_index=idx)
            db_session.add(link)
        await db_session.commit()

        # 4. Publish training job payload to RabbitMQ (async, non-blocking)
        connection = await aio_pika.connect_robust(
            host=RABBITMQ_HOST,
            port=5672,
        )
        async with connection:
            channel = await connection.channel()
            queue = await channel.declare_queue("trainer-queue", durable=True)
            await channel.default_exchange.publish(
                aio_pika.Message(
                    body=json.dumps({
                        "model_id": str(model.id_model),
                        "nombre": model.nombre,
                        "piezas": [
                            {
                                "id_pieza": str(p_id),
                                "class_index": idx
                            } for idx, p_id in enumerate(request.piezas)
                        ]
                    }).encode(),
                    delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
                ),
                routing_key="trainer-queue",
            )

        return {
            "model_id": str(model.id_model),
            "nombre": model.nombre,
            "estado": model.estado,
            "message": "Training job queued successfully"
        }

@router.get("/models", response_model=List[VisionModelListEntry])
async def list_models():
    """Return all vision models with a piece count, newest first."""
    async with AsyncSessionLocal() as session:
        result = await session.exec(
            select(VisionModel, func.count(ModelPiezaLink.id_pieza))
            .outerjoin(ModelPiezaLink, ModelPiezaLink.id_model == VisionModel.id_model)
            .group_by(VisionModel.id_model)
            .order_by(VisionModel.created_at.desc().nullslast())
        )

        entries: List[VisionModelListEntry] = []
        for model, piezas_count in result.all():
            entries.append(VisionModelListEntry(
                id_model=model.id_model,
                nombre=model.nombre,
                estado=model.estado,
                created_at=model.created_at,
                completed_at=model.completed_at,
                piezas_count=piezas_count or 0,
                key_s3_weights=model.key_s3_weights,
            ))
        return entries


@router.get("/models/{model_id}", response_model=VisionModelDetail)
async def get_model(model_id: uuid.UUID):
    """Return a single vision model with its piezas (id, nombre, class_index)."""
    async with AsyncSessionLocal() as session:
        model = await session.get(VisionModel, model_id)
        if not model:
            raise HTTPException(status_code=404, detail=f"Model {model_id} not found")

        link_result = await session.exec(
            select(ModelPiezaLink, Pieza.nombre)
            .join(Pieza, Pieza.id_pieza == ModelPiezaLink.id_pieza, isouter=True)
            .where(ModelPiezaLink.id_model == model_id)
            .order_by(ModelPiezaLink.class_index.asc())
        )

        piezas_entries: List[ModelPiezaEntry] = []
        for link, pieza_nombre in link_result.all():
            piezas_entries.append(ModelPiezaEntry(
                id_pieza=link.id_pieza,
                nombre=pieza_nombre,
                class_index=link.class_index,
            ))

        return VisionModelDetail(
            id_model=model.id_model,
            nombre=model.nombre,
            estado=model.estado,
            created_at=model.created_at,
            completed_at=model.completed_at,
            piezas_count=len(piezas_entries),
            key_s3_weights=model.key_s3_weights,
            piezas=piezas_entries,
        )


@router.post("/find-objects")
async def find_objects(file: UploadFile = File(...)): 
    image_bytes = await file.read()
    image = Image.open(io.BytesIO(image_bytes))
    # res = inferir(PATH_MODELO, image)
    # print(res)
    return {"message": "Inference template endpoint"}
