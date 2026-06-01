from fastapi import APIRouter, Form, File, UploadFile, HTTPException
import os
import uuid
import json
import zipfile
import shutil
import pika
from pathlib import Path
from typing import List

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
    opaque: bool = Form(False),
    # ── Real image upload (optional) ──────────────────────────────────────────
    # Flat list of real photo files. Variants are passed as a parallel JSON
    # array in real_images_variants (same length). Each entry in variants
    # corresponds to the image at the same index in real_images.
    # Example: 10 sin_bolsa images + 5 con_bolsa_clear images →
    #   real_images       = [img0, img1, ..., img14]
    #   real_images_variants = ["sin_bolsa"]*10 + ["con_bolsa_clear"]*5
    real_images: List[UploadFile] = File(default=[]),
    real_images_variants: str = Form(default="[]"),
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

    # Parse real image variants; fall back to sin_bolsa for any missing entry
    try:
        variants_list: List[str] = json.loads(real_images_variants)
    except (json.JSONDecodeError, TypeError):
        variants_list = []

    def get_variant(idx: int) -> str:
        if idx < len(variants_list):
            return variants_list[idx]
        return "sin_bolsa"

    # Generate new Pieza internally in SQL database
    async with AsyncSessionLocal() as db_session:
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
        r.setex(f"prompt:{taskID}", 864000, prompt)

        # ── 3D model → Blender queue ───────────────────────────────────────────
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
                raise HTTPException(status_code=400, detail="No .obj file found in zip")
            path = str(objFiles[0])

        r.setex(f"path:{taskID}", 864000, path)
        r.setex(f"status:{taskID}", 864000, "QUEUED")

        connection = pika.BlockingConnection(
            pika.ConnectionParameters(
                host=RABBITMQ_HOST,
                connection_attempts=3,
                retry_delay=2
            )
        )
        channel = connection.channel()
        channel.queue_declare(queue="blender-queue", durable=True)
        channel.queue_declare(queue="grounding-sam-queue", durable=True)

        channel.basic_publish(
            exchange='',
            routing_key="blender-queue",
            body=json.dumps({
                "task_id": taskID,
                "scene_file": path,
                "prompt": prompt,
                "bag_types": bagTypes,
            }),
            properties=pika.BasicProperties(delivery_mode=2)
        )

        # ── Real images → Grounding-SAM queue ─────────────────────────────────
        # Real images go into /app/data/{taskID}/real/ and are queued directly
        # to the DINO/SAM worker. They share the same task ID so operators review
        # both synthetic frames and real photos in a single validation session.
        real_dir = os.path.join(task_dir, "real")
        real_count = 0
        if real_images:
            os.makedirs(real_dir, exist_ok=True)
            for i, real_img in enumerate(real_images):
                variant = get_variant(i)
                real_filename = f"real_{i}_{real_img.filename}"
                real_path = os.path.join(real_dir, real_filename)
                with open(real_path, "wb") as buf:
                    buf.write(await real_img.read())

                channel.basic_publish(
                    exchange='',
                    routing_key="grounding-sam-queue",
                    body=json.dumps({
                        "taskId": taskID,
                        "frame": f"real_{i}",
                        "path": real_path,
                        "variante": variant,    # read by updated dinoWorker
                    }),
                    properties=pika.BasicProperties(delivery_mode=2)
                )
                real_count += 1

            # Mark task as having real images so the UI can badge it
            r.setex(f"has_real:{taskID}", 864000, str(real_count))

        connection.close()

        return {
            "task_id": taskID,
            "status": "QUEUED",
            "bag_types": bagTypes,
            "real_images_queued": real_count,
            "message": "File received, validated and queued for processing",
        }
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))