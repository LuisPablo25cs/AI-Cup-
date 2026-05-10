
from fastapi import FastAPI, Form, File, UploadFile, HTTPException
from contextlib import asynccontextmanager
from src.db import test_connection, init_db
from src.routes.imagenRouter import router as imagenRouter
from src.routes.piezaRouter import router as piezaRouter
from src.routes.inspectRouter import router as inspectRouter
from src.services.kit_config import load_kit_config
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

Path("/app/data").mkdir(exist_ok=True)

def connect_rabbitmq(retries=10, delay=5):
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

conn = connect_rabbitmq()
channel = conn.channel()
channel.queue_declare(queue="blender-queue", durable=True)
channel.queue_declare(queue="grounding-sam-queue", durable=True)


r = redis.Redis(host="redis", port=6379, db=0)

fileTypes = [
    "model/gltf-binary",      # .glb MIME type
    "application/octet-stream" # fallback some clients send for .glb
]

#PATH_MODELO = "yolov8n-seg.pt"
#def inferir(model, img): 
    #model = YOLO(model)
    #resultado = model(img)
    #return resultado

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Server is starting")
    await test_connection()
    await init_db()
    # Load kit config — raises ValueError on missing/invalid file (REQ-14).
    # No try/except: let it crash so uvicorn refuses to start.
    config_path = Path("/app/models_config.json")
    app.state.kits_config = load_kit_config(config_path)
    print(f"Loaded kit config from {config_path} ({len(app.state.kits_config.root)} kit(s))")
    yield
    print("Server is closing")

app = FastAPI(lifespan=lifespan)

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
    taskID = str(uuid.uuid4())
    try:
        r.setex(f"class_id:{taskID}", 1800, "0")
        r.setex(f"file:{taskID}", 1800, file.filename)
        path = f"/app/data/{file.filename}"
        with open(path, "wb") as buffer: 
            buffer.write(await file.read())
        r.setex(f"prompt:{taskID}", 1800, prompt)
        r.setex(f"path:{taskID}", 1800, path)
        r.setex(f"status:{taskID}", 1800, "QUEUED")
        channel.basic_publish(
            exchange='', 
            routing_key="blender-queue", 
            body=json.dumps({
                "task_id" : taskID,
                "scene_file" : path, 
                "prompt" : prompt, 
                "n_images" : 8
            }))
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
        return {
            "error" : "task not fouund"
        }, 404
    status = status.decode()
    pending = []
    for key in r.scan_iter("staging:*"):
        data = json.loads(r.get(key))
        if data["status"] == "pending_validation":
            pending.append(data)
    if len(pending) == 0: 
        return {
        
            "task_id": taskID,
            "status": status,
            "message": "File received, validated and queued for processing"
        }
    return pending

@app.post("/confirm/{taskID}")
async def confirm(taskID, imgStatus):
    status = r.get(f"status:{taskID}") 
    if not status: 
        return {
            "error" : "task not fouund"
        }, 404
    total = imgStatus.count()
    approved = 0
    for img in imgStatus: 
        if img.status == "aproved":
            approved +=1
            #logic to store
            print("Aproved")
        elif img.status == "not_aproved":
            #logic to delete
            print("Deleted")
        else: 
            print("Inapropiate format")
    #Transaction logic
    transaction_status = False
    return {
        "task_id" : taskID,
        "transaction_status" : transaction_status, 
        "Amount_approved" : f"{approved} / {total}"
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
app.include_router(inspectRouter)