from sqlmodel import SQLModel, Field, Relationship
import sqlalchemy.dialects.postgresql as pg
from sqlalchemy import Column as Column, DateTime
from uuid import UUID, uuid4
from datetime import datetime, timezone

"""
    A YOLO segmentation annotation (.txt file in S3).
    
    One Label per RenderSet (1-to-1 with RenderSet, 1-to-many with Imagen).

    S3 path: piezas/{id_pieza}/{id_render_set}/label.txt
"""

class Label(SQLModel, table=True):

    __tablename__ = "label"

    id_label: UUID = Field(
        sa_column=Column(pg.UUID, primary_key=True, unique=True, default=uuid4)
    )

    # 1-to-1 with RenderSet
    id_render_set: UUID = Field(
        foreign_key="render_set.id_render_set",
        unique=True,
        index=True
    )

    #S3
    bucket: str
    key_s3: str  # piezas/{id_pieza}/{id_render_set}/label.txt

    #Metadata
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    )

    # Relationships
    render_set: "RenderSet" = Relationship(back_populates="label")
    imagenes: list["Imagen"] = Relationship(back_populates="label")
