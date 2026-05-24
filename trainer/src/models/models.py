from sqlmodel import SQLModel, Field, Relationship
import sqlalchemy.dialects.postgresql as pg
from sqlalchemy import Column as SAColumn, DateTime, ForeignKey
from uuid import UUID, uuid4
from datetime import datetime, timezone
from enum import Enum
from typing import Optional, List

class BagVariant(str, Enum):
    SIN_BOLSA = "sin_bolsa"
    CON_BOLSA_CLEAR = "con_bolsa_clear"
    CON_BOLSA_OPAQUE = "con_bolsa_opaque"

class ModelPiezaLink(SQLModel, table=True):
    __tablename__ = "model_pieza_link"
    
    id_model: UUID = Field(
        sa_column=SAColumn(pg.UUID, ForeignKey("vision_model.id_model"), primary_key=True)
    )
    id_pieza: UUID = Field(
        sa_column=SAColumn(pg.UUID, ForeignKey("pieza.id_pieza"), primary_key=True)
    )
    class_index: int

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

    pieza: Pieza = Relationship(back_populates="render_sets")
    label: Optional["Label"] = Relationship(back_populates="render_set")
    imagenes: List["Imagen"] = Relationship(back_populates="render_set")


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

    render_set: RenderSet = Relationship(back_populates="label")
    imagenes: List["Imagen"] = Relationship(back_populates="label")


class Imagen(SQLModel, table=True):
    __tablename__ = "imagen"

    id_imagen: UUID = Field(
        sa_column=SAColumn(pg.UUID, primary_key=True, unique=True, default=uuid4)
    )
    id_render_set: UUID = Field(foreign_key="render_set.id_render_set", index=True)
    id_label: UUID | None = Field(
        default=None,
        foreign_key="label.id_label",
        nullable=True,
        index=True
    )
    variante: BagVariant
    bucket: str
    key_s3: str
    created_at: datetime = Field(
        sa_column=SAColumn(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    )

    render_set: RenderSet = Relationship(back_populates="imagenes")
    label: Optional[Label] = Relationship(back_populates="imagenes")


class VisionModel(SQLModel, table=True):
    __tablename__ = "vision_model"

    id_model: UUID = Field(
        sa_column=SAColumn(pg.UUID, primary_key=True, unique=True, default=uuid4)
    )
    nombre: str
    version: int = 1
    estado: str = "QUEUED"  # QUEUED, PREPARING_DATA, TRAINING, COMPLETED, FAILED
    key_s3_weights: str | None = None
    created_at: datetime = Field(
        sa_column=SAColumn(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    )
    completed_at: datetime | None = Field(
        sa_column=SAColumn(DateTime(timezone=True), nullable=True)
    )