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
    activo: bool = True
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=SAColumn(DateTime(timezone=True))
    )
    edited_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=SAColumn(DateTime(timezone=True))
    )
    # Relationships

    #Tiene renders
    render_sets: list["RenderSet"] = Relationship(back_populates="pieza")
