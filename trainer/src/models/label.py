from sqlmodel import SQLModel, Field, Relationship
import sqlalchemy.dialects.postgresql as pg
from sqlalchemy import Column as SAColumn, DateTime
from uuid import UUID, uuid4
from datetime import datetime, timezone
from typing import List

class Label(SQLModel, table=True):
    __tablename__ = "label"

    id_label: UUID = Field(
        sa_column=SAColumn(pg.UUID, primary_key=True, unique=True, default=uuid4)
    )
    id_render_set: UUID = Field(
        foreign_key="render_set.id_render_set",
        unique=True,
        index=True
    )
    bucket: str
    key_s3: str

    created_at: datetime = Field(
        sa_column=SAColumn(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    )

    render_set: "RenderSet" = Relationship(back_populates="label")
    imagenes: List["Imagen"] = Relationship(back_populates="label")