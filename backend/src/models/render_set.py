from sqlmodel import SQLModel, Field, Relationship
import sqlalchemy.dialects.postgresql as pg
from sqlalchemy import Column, DateTime
from uuid import UUID, uuid4
from datetime import datetime, timezone
from typing import Optional


"""
    Groups all image variants (sin_bolsa, con_bolsa_clear, etc.) rendered under
    identical conditions, so they share a single YOLO label.
    
    frame_name encodes the full rendering config, e.g.:
        "azul_oscuro_brillante_alto_atras"  (fondo_perfil_vista)
        "hdri_outdoor_frente"               (hdri_name_vista)
    """

class RenderSet(SQLModel, table=True):
    
    __tablename__ = "render_set"

    id_render_set: UUID = Field(
        sa_column=Column(pg.UUID, primary_key=True, unique=True, default=uuid4)
    )
    id_pieza: UUID = Field(foreign_key="pieza.id_pieza", index=True)

    # Full composite name from renderScene.py: fondo_perfil_vista or hdri_name_vista
    frame_name: str

    # Origin of this render set: "synthetic" (Blender render) or "real" (uploaded photo).
    # Defaults to "synthetic" so all existing rows are unaffected.
    source: str = Field(default="synthetic")

    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    )

    # Relationships
    pieza: "Pieza" = Relationship(back_populates="render_sets")
    label: Optional["Label"] = Relationship(back_populates="render_set")
    imagenes: list["Imagen"] = Relationship(back_populates="render_set")

