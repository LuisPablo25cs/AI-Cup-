import os
from pathlib import Path
import torch
from dotenv import load_dotenv

# Load environment variables from .env if present
load_dotenv()

class Config:
    # Database Configuration
    DATABASE_URL: str = os.getenv("DATABASE_URL", "postgresql://admin:admin@db:5432/kitting_db")
    
    @property
    def ASYNC_DATABASE_URL(self) -> str:
        # Replaces postgresql:// with postgresql+asyncpg:// for async pg driver
        if self.DATABASE_URL.startswith("postgresql://"):
            return self.DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)
        return self.DATABASE_URL

    # AWS S3 Configuration
    AWS_ACCESS_KEY_ID: str | None = os.getenv("AWS_ACCESS_KEY_ID")
    AWS_SECRET_ACCESS_KEY: str | None = os.getenv("AWS_SECRET_ACCESS_KEY")
    AWS_REGION: str = os.getenv("AWS_REGION", "us-east-1")
    S3_BUCKET_NAME: str = os.getenv("S3_BUCKET_NAME", "ai-cup-bucket")

    # RabbitMQ Configuration
    RABBITMQ_HOST: str = os.getenv("RABBITMQ_HOST", "rabbitmq")
    RABBITMQ_QUEUE: str = "trainer-queue"

    # Comet ML Configuration
    COMET_API_KEY: str | None = os.getenv("COMET_API_KEY")
    COMET_PROJECT_NAME: str = os.getenv("COMET_PROJECT_NAME", "AI-CUP")
    COMET_WORKSPACE: str | None = os.getenv("COMET_WORKSPACE")

    # YOLO Training Hyperparameters
    BASE_MODEL: str = os.getenv("YOLO_BASE_MODEL", "yolov8n-seg.pt")
    TRAIN_EPOCHS: int = int(os.getenv("TRAIN_EPOCHS", "100"))
    TRAIN_PATIENCE: int = int(os.getenv("TRAIN_PATIENCE", "15"))
    TRAIN_IMGSZ: int = int(os.getenv("TRAIN_IMGSZ", "640"))
    
    # Path configuration
    WORKSPACE_DIR: Path = Path(os.getenv("WORKSPACE_DIR", "/app/workspace"))
    S3_CACHE_DIR: Path = Path(os.getenv("S3_CACHE_DIR", str(WORKSPACE_DIR / "s3_cache")))

    # Hardware Acceleration
    @property
    def DEVICE(self) -> str:
        if torch.cuda.is_available():
            return "0"
        return "cpu"

config = Config()

# Ensure workspace directory exists at startup
config.WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
config.S3_CACHE_DIR.mkdir(parents=True, exist_ok=True)