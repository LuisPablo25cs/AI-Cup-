from sqlmodel import SQLModel, Field, Relationship
from uuid import UUID, uuid4
from datetime import datetime, timezone
import sqlalchemy.dialects.postgresql as pg
from sqlalchemy import Column as SAColumn
from sqlalchemy import DateTime


"""Placeholder VisionModel model class while we figure out the pipeline

"""

class VisionModel(SQLModel, table=True):
    __tablename__ = "vision_model"
    
    id_model: UUID = Field(
        sa_column=SAColumn(pg.UUID, primary_key=True, unique=True, default=uuid4)
    )
    nombre: str
    version: int = 1

    #S3
    bucket: str
    key_s3: str  # models/uuid.pt
    
    created_at: datetime = Field(
        sa_column=SAColumn(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    )
