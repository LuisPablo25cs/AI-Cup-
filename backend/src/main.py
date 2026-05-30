from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
from pathlib import Path
import os
import logging

from src.db import test_connection, init_db
from src.routes.imagenRouter import router as imagenRouter
from src.routes.piezaRouter import router as piezaRouter
from src.routes.scanRouter import router as scanRouter
from src.routes.taskRouter import router as taskRouter
from src.routes.visionModelRouter import router as visionModelRouter
from src.routes.kitRouter import router as kitRouter
from src.routes.inspeccionRouter import router as inspeccionRouter


class AdminKeySanitizer(logging.Filter):
    """Redact ADMIN_DELETE_KEY value from all log messages."""

    def __init__(self, name: str = "") -> None:
        super().__init__(name)
        self._secret = os.getenv("ADMIN_DELETE_KEY")

    def filter(self, record: logging.LogRecord) -> bool:
        if self._secret and isinstance(record.msg, str) and self._secret in record.msg:
            record.msg = record.msg.replace(self._secret, "[REDACTED]")
        return True


# Apply sanitizer to root logger so all loggers are covered.
logging.getLogger().addFilter(AdminKeySanitizer())

Path("/app/data").mkdir(exist_ok=True)



@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Server is starting")
    await test_connection()
    await init_db()

    # Warn if admin delete key is not configured (spec AKG-003)
    admin_key = os.getenv("ADMIN_DELETE_KEY")
    if not admin_key:
        print(
            "WARNING: ADMIN_DELETE_KEY is not set. "
            "All DELETE endpoints will return 500 until configured."
        )
    else:
        print("ADMIN_DELETE_KEY is configured. DELETE endpoints are operational.")

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
