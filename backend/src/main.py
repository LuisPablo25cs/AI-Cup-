from fastapi import FastAPI, UploadFile, HTTPException
from contextlib import asynccontextmanager
from backend.src.db import test_connection, init_db
from backend.src.routes.imagenRouter import router as imagenRouter
from backend.src.routes.piezaRouter import router as piezaRouter
import pika
import io
import redis 
import uuid
import os
from PIL import Image
from ultralytics import YOLO
import json

#Connection with rabbitmq
conn = pika.BlockingConnection(pika.ConnectionParameters(host="rabbitmq"))
#Start TCP conn with rabbitmq
channel = conn.channel()
#Declare queues 
channel.queue_declare(queue="blender-queue", durable=True)
channel.queue_declare(queue="grounding-sam-queue", durable=True)

r = redis.Redis(host="redis", port=6379, db=0)
#toDo
fileTypes = {

}

PATH_MODELO = "yolov8n-seg.pt"
def inferir(model, img): 
    model = YOLO(model)
    resultado = model(img)
    return resultado

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Server is starting")
    await test_connection()
    await init_db()
    yield
    print("Server is closing")

app = FastAPI(lifespan=lifespan)

@app.get("/health")
def health():
    return {"message": "healthy"}


@app.post("/publishNewPiece")
async def publishNewPiece(file: UploadFile, prompt: str): 
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
        r.setex(f"file:{taskID}, 1800, {file.filename}")
        path = f"/app/data{file.filename}"
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
    except Exception as e:
        return {
            "task_id": taskID,
            "status": "QUEUED",
            "message": "File received, validated and queued for processing"}, 202


#Template for inference endpoint 

@app.post("/find-objects")
async def find_objects(file: UploadFile = File(...)): 
    image_bytes = await file.read()
    image = Image.open(io.BytesIO(image_bytes))
    res = inferir(PATH_MODELO, image)
    print(res)

app.include_router(imagenRouter)
app.include_router(piezaRouter)