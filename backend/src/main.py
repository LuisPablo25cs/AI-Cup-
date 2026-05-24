from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
from pathlib import Path
import time
import pika

from src.db import test_connection, init_db
from src.routes.imagenRouter import router as imagenRouter
from src.routes.piezaRouter import router as piezaRouter
from src.routes.scanRouter import router as scanRouter
from src.routes.taskRouter import router as taskRouter
from src.routes.visionModelRouter import router as visionModelRouter

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

app.include_router(imagenRouter)
app.include_router(piezaRouter)
app.include_router(scanRouter)
app.include_router(taskRouter)
app.include_router(visionModelRouter)