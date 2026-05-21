import pika
import os
import time
import json
import uuid
import boto3
import redis
import shutil
import random
from pathlib import Path
from datetime import datetime, timezone
from ultralytics import YOLO

# Postgres client setup
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import SQLModel, Field, select

channel = conn.channel()
#toDo-If you see all of this be very sceptical of how this works, this is only a template
channel.queue_declare(queue="blender-queue", durable=True)

r = redis.Redis(host="redis", port=6379, db=0)

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://admin:admin@db:5432/kitting_db")
ASYNC_DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://")

asyncEngine = create_async_engine(url=ASYNC_DATABASE_URL, echo=False)
AsyncSessionLocal = async_sessionmaker(asyncEngine, class_=AsyncSession, expire_on_commit=False)

# SQLModel lightweight declarations for querying PostgreSQL
class Pieza(SQLModel, table=True):
    __tablename__ = "pieza"
    id_pieza: uuid.UUID = Field(primary_key=True)
    nombre: str

class Imagen(SQLModel, table=True):
    __tablename__ = "imagen"
    id_imagen: uuid.UUID = Field(primary_key=True)
    id_pieza: uuid.UUID = Field(foreign_key="pieza.id_pieza")
    bucket: str
    key_s3: str
    key_s3_label: str | None = None

class VisionModel(SQLModel, table=True):
    __tablename__ = "vision_model"
    id_model: uuid.UUID = Field(primary_key=True)
    nombre: str
    estado: str
    key_s3_weights: str | None = None
    completed_at: datetime | None = None

# S3 Setup
s3_client = boto3.client(
    "s3",
    aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
    aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
    region_name=os.getenv("AWS_REGION")
)
BUCKET_NAME = os.getenv("S3_BUCKET_NAME")

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

async def update_model_status(model_id: uuid.UUID, status: str, s3_key: str | None = None):
    async with AsyncSessionLocal() as session:
        model = await session.get(VisionModel, model_id)
        if model:
            model.estado = status
            if s3_key:
                model.key_s3_weights = s3_key
                model.completed_at = datetime.now(timezone.utc)
            session.add(model)
            await session.commit()
            print(f"VisionModel {model_id} updated to {status}")

async def run_training_pipeline(model_id: uuid.UUID, model_name: str, pieces: list):
    dataset_dir = Path(f"/app/dataset_{model_id}")
    images_train_dir = dataset_dir / "images" / "train"
    images_val_dir = dataset_dir / "images" / "val"
    labels_train_dir = dataset_dir / "labels" / "train"
    labels_val_dir = dataset_dir / "labels" / "val"

    # Create directory tree
    images_train_dir.mkdir(parents=True, exist_ok=True)
    images_val_dir.mkdir(parents=True, exist_ok=True)
    labels_train_dir.mkdir(parents=True, exist_ok=True)
    labels_val_dir.mkdir(parents=True, exist_ok=True)

    try:
        await update_model_status(model_id, "TRAINING")
        
        class_names = {}
        all_samples = []

        # 1. Fetch images and labels from S3
        async with AsyncSessionLocal() as session:
            for piece_info in pieces:
                p_id = uuid.UUID(piece_info["id_pieza"])
                class_idx = piece_info["class_index"]
                
                # Get piece metadata to fill names in dataset.yaml
                piece_obj = await session.get(Pieza, p_id)
                class_names[class_idx] = piece_obj.nombre if piece_obj else f"class_{class_idx}"

                # Query database for all images linked to this Piece
                stmt = select(Imagen).where(Imagen.id_pieza == p_id)
                images_query = await session.exec(stmt)
                images = images_query.all()
                print(f"Piece {class_names[class_idx]} has {len(images)} images.")

                for img in images:
                    if not img.key_s3_label:
                        print(f"Skipping image {img.id_imagen} because it has no S3 label.")
                        continue
                    
                    all_samples.append({
                        "id": str(img.id_imagen),
                        "key_s3": img.key_s3,
                        "key_s3_label": img.key_s3_label,
                        "class_index": class_idx
                    })

        if not all_samples:
            raise Exception("No annotated images found for the selected pieces.")

        # Shuffle and split into Train (80%) and Val (20%)
        random.shuffle(all_samples)
        split_idx = int(len(all_samples) * 0.8)
        train_samples = all_samples[:split_idx]
        val_samples = all_samples[split_idx:]

        def download_and_format(samples, is_train: bool):
            target_img_dir = images_train_dir if is_train else images_val_dir
            target_lbl_dir = labels_train_dir if is_train else labels_val_dir

            for sample in samples:
                local_img_path = target_img_dir / f"{sample['id']}.jpg"
                local_lbl_path = target_lbl_dir / f"{sample['id']}.txt"

                # Download Image
                s3_client.download_file(BUCKET_NAME, sample["key_s3"], str(local_img_path))
                
                # Download and dynamically format YOLO annotation with corrected class index
                temp_lbl_path = target_lbl_dir / f"temp_{sample['id']}.txt"
                s3_client.download_file(BUCKET_NAME, sample["key_s3_label"], str(temp_lbl_path))
                
                # Rewrite class indices in the annotation label
                with open(temp_lbl_path, "r") as f:
                    lines = f.readlines()
                
                new_lines = []
                for line in lines:
                    parts = line.strip().split()
                    if parts:
                        parts[0] = str(sample["class_index"])
                        new_lines.append(" ".join(parts) + "\n")
                
                with open(local_lbl_path, "w") as f:
                    f.writelines(new_lines)
                
                temp_lbl_path.unlink()

        # Download train/val splits
        print("Downloading training split...")
        download_and_format(train_samples, is_train=True)
        print("Downloading validation split...")
        download_and_format(val_samples, is_train=False)

        # 2. Create dataset.yaml
        yaml_content = f"""
path: {dataset_dir}
train: images/train
val: images/val
names:
"""
        for class_idx, name in class_names.items():
            yaml_content += f"  {class_idx}: {name}\n"

        yaml_path = dataset_dir / "dataset.yaml"
        with open(yaml_path, "w") as f:
            f.write(yaml_content)

        # 3. Train YOLO Model (using a fast, robust 5 epochs for testing)
        print("Initializing YOLO segmentation training...")
        model = YOLO("yolov8n-seg.pt")
        
        # Train model
        model.train(
            data=str(yaml_path),
            epochs=5,
            imgsz=640,
            project=str(dataset_dir / "runs"),
            name="train"
        )

        # 4. Upload best weights back to S3
        best_weights_path = dataset_dir / "runs" / "train" / "weights" / "best.pt"
        if not best_weights_path.exists():
            raise Exception("Training finished but weights file was not generated.")

        s3_key_weights = f"models/{model_id}/best.pt"
        print(f"Uploading best weights to S3: {s3_key_weights}")
        s3_client.upload_file(str(best_weights_path), BUCKET_NAME, s3_key_weights)

        # 5. Mark Model completed in Postgres
        await update_model_status(model_id, "COMPLETED", s3_key=s3_key_weights)

    except Exception as e:
        print(f"Training failed: {e}")
        await update_model_status(model_id, "FAILED")
    finally:
        # 6. Clean up temporary files on disk
        if dataset_dir.exists():
            shutil.rmtree(dataset_dir)

def on_training_job(ch, method, properties, body):
    job = json.loads(body)
    model_id = uuid.UUID(job["model_id"])
    model_name = job["nombre"]
    pieces = job["piezas"]

    print(f"Received training request: {model_name} (ID: {model_id})")
    
    # Send acknowledgment immediately to prevent RabbitMQ heartbeats from timing out during long training
    ch.basic_ack(delivery_tag=method.delivery_tag)
    
    # Run the training logic synchronously inside python thread
    import asyncio
    asyncio.run(run_training_pipeline(model_id, model_name, pieces))

def main():
    conn = connect_rabbitmq()
    channel = conn.channel()
    channel.queue_declare(queue="trainer-queue", durable=True)
    channel.basic_qos(prefetch_count=1)
    
    print("Trainer Consumer is ready and waiting for jobs...")
    channel.basic_consume(queue="trainer-queue", on_message_callback=on_training_job)
    channel.start_consuming()

if __name__ == "__main__":
    main()
