from fastapi import APIRouter, Form, File, UploadFile, HTTPException
import os
import uuid
import json
import zipfile
import shutil
import pika
from pathlib import Path

from src.db import AsyncSessionLocal
from src.models.pieza import Pieza
from src.core.config import r, fileTypes

router = APIRouter(prefix="/3D-scans", tags=["3D Scans"])

RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "localhost")

@router.post("/publishNewPiece")
async def publishNewPiece(
    prompt: str = Form(), 
    file: UploadFile = File(...),
    clear: bool = Form(False),
    opaque: bool = Form(False)
):
    if file.content_type not in fileTypes: 
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: {file.content_type}"
        )
    if not file: 
        raise HTTPException(
            status_code=415, 
            detail=f"Please provide a file: {file}"
        )
    
    bagTypes = []
    if clear: 
        bagTypes.append("clear")
    if opaque:
        bagTypes.append("opaque")

    # Generate new Pieza internally in SQL database
    async with AsyncSessionLocal() as db_session:
        # Use filename as piece name and prompt as description
        nombre_pieza = file.filename.rsplit(".", 1)[0]
        new_pieza = Pieza(nombre=nombre_pieza, descripcion=prompt)
        db_session.add(new_pieza)
        await db_session.commit()
        await db_session.refresh(new_pieza)
        pieza_id = new_pieza.id_pieza

    taskID = str(uuid.uuid4())
    task_dir = os.path.join("/app/data", taskID)
    os.makedirs(task_dir, exist_ok=True)
    
    try:
        r.setex(f"class_id:{taskID}", 864000, str(pieza_id))
        r.setex(f"file:{taskID}", 864000, file.filename)
        r.setex(f"bag_type:{taskID}", 864000, json.dumps(bagTypes))
        path = os.path.join(task_dir, file.filename)

        with open(path, "wb") as buffer: 
            buffer.write(await file.read())

        if file.filename.lower().endswith(".zip"): 
            with zipfile.ZipFile(path, 'r') as zip_ref: 
                zip_ref.extractall(task_dir)
            os.remove(path)
            objFiles = list(Path(task_dir).glob("**/*.obj"))
            if not objFiles: 
                shutil.rmtree(task_dir)
                raise HTTPException(status_code=400, detail="No .obj file founded in zip")
            #This is the .obj path
            path = str(objFiles[0])

        r.setex(f"prompt:{taskID}", 864000, prompt)
        r.setex(f"path:{taskID}", 864000, path)
        r.setex(f"status:{taskID}", 864000, "QUEUED")
        
        connection = pika.BlockingConnection(
            pika.ConnectionParameters(host=RABBITMQ_HOST)
        )
        channel = connection.channel()
        channel.queue_declare(queue="blender-queue", durable=True)
        channel.basic_publish(
            exchange='', 
            routing_key="blender-queue", 
            body=json.dumps({
                "task_id": taskID,
                "scene_file": path, 
                "prompt": prompt, 
                "bag_types" : bagTypes,
            }),
            properties=pika.BasicProperties(delivery_mode=2) # Persistent message
        )
        connection.close()
        
        return {
            "task_id": taskID,
            "status": "QUEUED",
            "bag_types": bagTypes,
            "message": "File received, validated and queued for processing"
        }
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))