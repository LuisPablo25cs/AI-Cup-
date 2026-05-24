from sqlmodel import SQLModel, Field, Relationship
import sqlalchemy.dialects.postgresql as pg
from sqlalchemy import Column as SAColumn, DateTime
from uuid import UUID, uuid4
from datetime import datetime, timezone
from typing import Optional, List

class RenderSet(SQLModel, table=True):
    __tablename__ = "render_set"

    id_render_set: UUID = Field(
        sa_column=SAColumn(pg.UUID, primary_key=True, unique=True, default=uuid4)
    )
    id_pieza: UUID = Field(foreign_key="pieza.id_pieza", index=True)
    frame_name: str
    created_at: datetime = Field(
        sa_column=SAColumn(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    )

    pieza: "Pieza" = Relationship(back_populates="render_sets")
    label: Optional["Label"] = Relationship(back_populates="render_set")
    imagenes: List["Imagen"] = Relationship(back_populates="render_set")