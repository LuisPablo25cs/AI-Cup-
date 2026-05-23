
from fastapi import FastAPI, Form, File, UploadFile, HTTPException
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
from src.db import test_connection, init_db, AsyncSessionLocal
from src.models.imagen import Imagen
from src.models.pieza import Pieza
from src.models.vision_model import VisionModel, ModelPiezaLink
from src.services.s3 import upload_imagen, upload_label
from sqlmodel import select
from src.routes.imagenRouter import router as imagenRouter
from src.routes.piezaRouter import router as piezaRouter
import pika
import io
import redis 
import uuid
import os
from PIL import Image
from ultralytics import YOLO
import json
import time
from pathlib import Path
from pydantic import BaseModel
from typing import List
import shutil
import zipfile
import shutil

Path("/app/data").mkdir(exist_ok=True)

def connect_rabbitmq(retries=10, delay=10):
    for attempt in range(retries):
        try:
            conn = pika.BlockingConnection(
                pika.ConnectionParameters(host="rabbitmq")
            )
            print("Connected to RabbitMQ")
            return conn
        except Exception as e:
            print(f"RabbitMQ not ready ({attempt+1}/{retries}), retrying in {delay}s...")
            time.sleep(delay)
    raise Exception("Could not connect to RabbitMQ after retries")




r = redis.Redis(host="redis", port=6379, db=0)

fileTypes = [
    "model/gltf-binary",      # .glb MIME type
    "application/octet-stream", # fallback some clients send for .glb
    "application/zip",
    "application/x-zim-compressed",
]

#PATH_MODELO = "yolov8n-seg.pt"
#def inferir(model, img): 
    #model = YOLO(model)
    #resultado = model(img)
    #return resultado

#Classes 
class ImageConfirmation(BaseModel):
    frame: str
    status: str

class GenerateModelRequest(BaseModel):
    nombre: str
    piezas: List[uuid.UUID]
    
@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Server is starting")
    await test_connection()
    await init_db()
    yield
    print("Server is closing")

app = FastAPI(lifespan=lifespan)
app.mount("/staging", StaticFiles(directory="/staging"), name="staging")
@app.get("/health")
def health():
    return {"message": "healthy"}


@app.post("/publishNewPiece")
async def publishNewPiece(prompt: str = Form(), file: UploadFile = File(...)): 
    if file.content_type not in fileTypes: 
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: {file.content_type}"
        )
    if not file: 
        raise HTTPException(
            status_code = 415, 
            detail=f"Please provide a file: {file}"
        )
    
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
        connection = pika.BlockingConnection(pika.ConnectionParameters(host="rabbitmq"))
        channel = connection.channel()
        channel.queue_declare(queue="blender-queue", durable=True)
        channel.basic_publish(
            exchange='', 
            routing_key="blender-queue", 
            body=json.dumps({
                "task_id": taskID,
                "scene_file": path, 
                "prompt": prompt, 
            }),
            properties=pika.BasicProperties(delivery_mode=2) # Persistent message
        )
        connection.close()
        return {
            "task_id": taskID,
            "status": "QUEUED",
            "message": "File received, validated and queued for processing"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))



@app.get("/fetchImages/{taskID}")
async def fetchImages(taskID: str): 
    status = r.get(f"status:{taskID}")
    if not status: 
        raise HTTPException(status_code=404, detail="Task not found")
    status = status.decode()
 
    keys = list(r.scan_iter(f"staging:{taskID}:*"))
    if not keys:
        return {
            "task_id": taskID,
            "status": status,
            "message": "File received, validated and queued for processing"
        }
    
  
    pipe = r.pipeline()
    for key in keys:
        pipe.get(key)
    raw_values = pipe.execute()
    
    pending = []
    for val in raw_values:
        if val:
            data = json.loads(val)
            if data.get("status") == "pending_validation":
                pending.append(data)
                
    if len(pending) == 0: 
        return {
            "task_id": taskID,
            "status": status,
            "message": "File received, validated and queued for processing"
        }
    return pending

@app.post("/confirm/{taskID}")
async def confirm(taskID: str, imgStatus: List[ImageConfirmation]):
    status = r.get(f"status:{taskID}") 
    if not status: 
        raise HTTPException(status_code=404, detail="Task not found")
        
    pieza_id = None
    class_raw = r.get(f"class_id:{taskID}")
    if class_raw:
        try:
            pieza_id = uuid.UUID(class_raw.decode())
        except ValueError:
            pass

    if not pieza_id:
        raise HTTPException(status_code=400, detail="Task is not linked to a valid Piece ID (UUID)")

    # Verify the piece actually exists in Postgres
    async with AsyncSessionLocal() as db_session:
        pieza_exists = await db_session.get(Pieza, pieza_id)
        if not pieza_exists:
            raise HTTPException(status_code=404, detail="The linked Piece does not exist in the database")

    total = len(imgStatus)
    approved = 0
    rejected = 0
    
    # Batch-fetch current keys to update them in a performant pipeline
    pipe = r.pipeline()
    for img in imgStatus:
        metaKey = f"staging:{taskID}:{img.frame}"
        pipe.get(metaKey)
    raw_values = pipe.execute()
    
    update_pipe = r.pipeline()
    has_updates = False
    
    for img, val in zip(imgStatus, raw_values):
        if not val:
            continue
            
        data = json.loads(val)
        normalized_status = img.status.strip().lower()
        
        local_img_path = data.get("local_path")
        local_txt_path = data.get("txt_path")
        local_visual_path = data.get("visual_path")
        
        if normalized_status in ("approved", "aproved"):
            approved += 1
            data["status"] = "approved"
            update_pipe.setex(f"staging:{taskID}:{img.frame}", 864000, json.dumps(data))
            has_updates = True
            
            # S3 and Postgres logic
            if local_img_path and os.path.exists(local_img_path):
                # 1. Read local files
                with open(local_img_path, "rb") as f_img:
                    img_bytes = f_img.read()
                
                txt_bytes = b""
                if local_txt_path and os.path.exists(local_txt_path):
                    with open(local_txt_path, "rb") as f_txt:
                        txt_bytes = f_txt.read()
                
                # 2. Upload to S3 sharing the exact same filename UUID
                img_uuid = str(uuid.uuid4())
                bucket, key_s3 = upload_imagen(img_bytes, str(pieza_id), filename_uuid=img_uuid)
                
                key_s3_label = None
                if txt_bytes:
                    _, key_s3_label = upload_label(txt_bytes, str(pieza_id), filename_uuid=img_uuid)
                
                # 3. Create database entry
                async with AsyncSessionLocal() as db_session:
                    db_img = Imagen(
                        id_pieza=pieza_id,
                        bucket=bucket,
                        key_s3=key_s3,
                        key_s3_label=key_s3_label
                    )
                    db_session.add(db_img)
                    await db_session.commit()
                    
                # 4. Clean up local files
                try:
                    os.remove(local_img_path)
                    if local_txt_path and os.path.exists(local_txt_path):
                        os.remove(local_txt_path)
                    if local_visual_path and os.path.exists(local_visual_path):
                        os.remove(local_visual_path)
                except Exception as err:
                    print(f"Error cleaning up staging files for Frame {img.frame}: {err}")
            
            print(f"Frame {img.frame} Approved and stored")
            
        elif normalized_status in ("rejected", "not_approved", "not_aproved"):
            rejected += 1
            data["status"] = "rejected"
            update_pipe.setex(f"staging:{taskID}:{img.frame}", 864000, json.dumps(data))
            has_updates = True
            
            # Clean up local files
            try:
                if local_img_path and os.path.exists(local_img_path):
                    os.remove(local_img_path)
                if local_txt_path and os.path.exists(local_txt_path):
                    os.remove(local_txt_path)
                if local_visual_path and os.path.exists(local_visual_path):
                    os.remove(local_visual_path)
            except Exception as err:
                print(f"Error cleaning up rejected files for Frame {img.frame}: {err}")
                
            print(f"Frame {img.frame} Rejected and cleaned")
        else:
            print(f"Inappropriate format/status for Frame {img.frame}: {img.status}")
            
    if has_updates:
        update_pipe.execute()
        
    transaction_status = True if (approved + rejected) == total else False
    task_dir = os.path.join("/staging", taskID)
    if os.path.exists(task_dir):
        try:
            shutil.rmtree(task_dir)
            print(f"Cleaned up staging folder: {task_dir}")
        except Exception as err:
            print(f"Error cleaning up staging folder {task_dir}: {err}")
    return {
        "task_id": taskID,
        "transaction_status": transaction_status, 
        "Amount_approved": f"{approved} / {total}"
    }

@app.post("/generateModel")
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



#Template for inference endpoint 

@app.post("/find-objects")
async def find_objects(file: UploadFile = File(...)): 
    image_bytes = await file.read()
    image = Image.open(io.BytesIO(image_bytes))
    #res = inferir(PATH_MODELO, image)
    #print(res)

app.include_router(imagenRouter)
app.include_router(piezaRouter)