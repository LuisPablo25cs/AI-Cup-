from fastapi import APIRouter, File, UploadFile, HTTPException
from typing import List
import pika
import json
import uuid
import io
from PIL import Image

from src.db import AsyncSessionLocal
from src.models.pieza import Pieza
from src.models.vision_model import VisionModel, ModelPiezaLink
from pydantic import BaseModel

class GenerateModelRequest(BaseModel):
    nombre: str
    piezas: List[uuid.UUID]

router = APIRouter(tags=["Vision Models"])

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

        # 4. Publish training job payload to RabbitMQ
        connection = pika.BlockingConnection(pika.ConnectionParameters(host="rabbitmq"))
        channel = connection.channel()
        channel.queue_declare(queue="trainer-queue", durable=True)
        channel.basic_publish(
            exchange='',
            routing_key="trainer-queue",
            body=json.dumps({
                "model_id": str(model.id_model),
                "nombre": model.nombre,
                "piezas": [
                    {
                        "id_pieza": str(p_id),
                        "class_index": idx
                    } for idx, p_id in enumerate(request.piezas)
                ]
            }),
            properties=pika.BasicProperties(delivery_mode=2) # Persistent message
        )
        connection.close()

        return {
            "model_id": str(model.id_model),
            "nombre": model.nombre,
            "estado": model.estado,
            "message": "Training job queued successfully"
        }

@router.post("/find-objects")
async def find_objects(file: UploadFile = File(...)): 
    image_bytes = await file.read()
    image = Image.open(io.BytesIO(image_bytes))
    # res = inferir(PATH_MODELO, image)
    # print(res)
    return {"message": "Inference template endpoint"}
