from sqlmodel import SQLModel, Field, Column, Relationship    
import sqlalchemy.dialects.postgresql as pg
from uuid import UUID, uuid4
from datetime import datetime, timezone
from sqlalchemy import Column as SAColumn
from sqlalchemy import DateTime


class Pieza(SQLModel, table=True):
    __tablename__ = "pieza"

    id_pieza: UUID = Field(
        sa_column=Column(pg.UUID, primary_key=True, unique=True, default=uuid4)
    )
    nombre: str
    descripcion: str | None = None
    cantidad_estimada: int = 1
    activo: bool = True
    created_at: datetime = Field(
    sa_column=SAColumn(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
)
    edited_at: datetime = Field(
    sa_column=SAColumn(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
)
    # Relationships
    imagenes: list["Imagen"] = Relationship(back_populates="pieza")
