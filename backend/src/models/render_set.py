from sqlmodel import SQLModel, Field, Relationship
import sqlalchemy.dialects.postgresql as pg
from sqlalchemy import Column, DateTime
from uuid import UUID, uuid4
from datetime import datetime, timezone


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

    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    )

    # Relationships
    label: "Label | None" = Relationship(back_populates="render_set")
    imagenes: list["Imagen"] = Relationship(back_populates="render_set")
