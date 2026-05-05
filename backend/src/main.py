from fastapi import FastAPI
from contextlib import asynccontextmanager
from backend.src.db import test_connection, init_db
from backend.src.routes.imagenRouter import router as imagenRouter
from backend.src.routes.piezaRouter import router as piezaRouter

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

app.include_router(imagenRouter)
app.include_router(piezaRouter)