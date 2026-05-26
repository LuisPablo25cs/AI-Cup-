from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
from pathlib import Path
import os
import time
import pika

from src.db import test_connection, init_db
from src.routes.imagenRouter import router as imagenRouter
from src.routes.piezaRouter import router as piezaRouter
from src.routes.scanRouter import router as scanRouter
from src.routes.taskRouter import router as taskRouter
from src.routes.visionModelRouter import router as visionModelRouter
from src.routes.kitRouter import router as kitRouter
from src.routes.inspeccionRouter import router as inspeccionRouter

Path("/app/data").mkdir(exist_ok=True)

RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "localhost")

def connect_rabbitmq(retries=10, delay=10):
    for attempt in range(retries):
        try:
            conn = pika.BlockingConnection(
                pika.ConnectionParameters(host=RABBITMQ_HOST)
            )
            print("Connected to RabbitMQ")
            return conn
        except Exception as e:
            print(f"RabbitMQ not ready ({attempt+1}/{retries}), retrying in {delay}s...")
            time.sleep(delay)
    raise Exception("Could not connect to RabbitMQ after retries")

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Server is starting")
    await test_connection()
    await init_db()
    yield
    print("Server is closing")

app = FastAPI(lifespan=lifespan)

CORS_ORIGINS = [
    o.strip()
    for o in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")
    if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/staging", StaticFiles(directory="/staging"), name="staging")

@app.get("/health")
def health():
    return {"message": "healthy"}

app.include_router(imagenRouter)
app.include_router(piezaRouter)
app.include_router(scanRouter)
app.include_router(taskRouter)
app.include_router(visionModelRouter)
app.include_router(kitRouter)
app.include_router(inspeccionRouter)
