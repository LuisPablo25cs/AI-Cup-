from sqlmodel import SQLModel, Field, Relationship
from uuid import UUID, uuid4
from datetime import datetime, timezone
import sqlalchemy.dialects.postgresql as pg
from sqlalchemy import Column as SAColumn
from sqlalchemy import DateTime

class ModelPiezaLink(SQLModel, table=True):
    __tablename__ = "model_pieza_link"
    
    id_model: UUID = Field(
        sa_column=SAColumn(pg.UUID, primary_key=True, foreign_key="vision_model.id_model")
    )
    id_pieza: UUID = Field(
        sa_column=SAColumn(pg.UUID, primary_key=True, foreign_key="pieza.id_pieza")
    )
    class_index: int  # YOLO class index (0, 1, 2, ...)

class VisionModel(SQLModel, table=True):
    __tablename__ = "vision_model"
    
    id_model: UUID = Field(
        sa_column=SAColumn(pg.UUID, primary_key=True, unique=True, default=uuid4)
    )
    nombre: str
    version: int = 1
    estado: str = "QUEUED"  # QUEUED, TRAINING, COMPLETED, FAILED
    key_s3_weights: str | None = None  # S3 path to the trained best.pt file
    
    created_at: datetime = Field(
        sa_column=SAColumn(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    )
    completed_at: datetime | None = Field(
        sa_column=SAColumn(DateTime(timezone=True), nullable=True)
    )
