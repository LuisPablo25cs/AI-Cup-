from sqlmodel import SQLModel, Field, Relationship
import sqlalchemy.dialects.postgresql as pg
from sqlalchemy import Column as SAColumn, DateTime
from uuid import UUID, uuid4
from datetime import datetime, timezone
from typing import List

class Pieza(SQLModel, table=True):
    __tablename__ = "pieza"

    id_pieza: UUID = Field(
        sa_column=SAColumn(pg.UUID, primary_key=True, unique=True, default=uuid4)
    )
    nombre: str
    descripcion: str | None = None
    activo: bool = True
    created_at: datetime = Field(
        sa_column=SAColumn(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    )
    edited_at: datetime = Field(
        sa_column=SAColumn(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    )

    render_sets: List["RenderSet"] = Relationship(back_populates="pieza")