from sqlmodel import SQLModel, Field, Column, Relationship
import sqlalchemy.dialects.postgresql as pg
from uuid import UUID, uuid4
from datetime import datetime, timezone
from sqlalchemy import Column as SAColumn
from sqlalchemy import DateTime


class Imagen(SQLModel, table=True):
    __tablename__ = "imagen"

    id_imagen: UUID = Field(
        sa_column=Column(pg.UUID, primary_key=True, unique=True, default=uuid4)
    )

    # FK a Pieza
    id_pieza: UUID = Field(foreign_key="pieza.id_pieza")

    # S3
    bucket: str                          # nombre del bucket
    key_s3: str                          # pieza/{id_pieza}/{uuid}.jpg

    # La URL completa se deriva: f"{bucket}/{key_s3}" — no se guarda en BD

    # Metadatos de imagen
    width: int | None = None
    height: int | None = None
    fecha_captura: datetime = Field(
    sa_column=SAColumn(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
)


    # Relationships
    pieza: "Pieza" = Relationship(back_populates="imagenes")
