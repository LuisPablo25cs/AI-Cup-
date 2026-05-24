from sqlmodel import SQLModel, Field, Relationship
import sqlalchemy.dialects.postgresql as pg
from uuid import UUID, uuid4
from datetime import datetime, timezone
from sqlalchemy import Column
from sqlalchemy import DateTime
from enum import Enum
from typing import Optional

class BagVariant(str, Enum):
    SIN_BOLSA = "sin_bolsa"
    CON_BOLSA_CLEAR = "con_bolsa_clear"
    CON_BOLSA_OPAQUE = "con_bolsa_opaque"



"""
    A single rendered image for one variant (sin_bolsa, con_bolsa_clear, etc.)
    within a RenderSet.
    S3 path: piezas/{id_pieza}/{id_render_set}/{variante}.jpg
    Variants: "sin_bolsa" | "con_bolsa_clear" | "con_bolsa_opaque"
    """


class Imagen(SQLModel, table=True):
    __tablename__ = "imagen"

    id_imagen: UUID = Field(
        sa_column=Column(pg.UUID, primary_key=True, unique=True, default=uuid4)
    )

    # FK to the shared render group
    id_render_set: UUID = Field(foreign_key="render_set.id_render_set", index=True)

    # FK to the shared YOLO annotation (nullable: set once label is confirmed)
    id_label: UUID | None = Field(
        default=None,
        foreign_key="label.id_label",
        nullable=True,
        index=True
    )

    variante: BagVariant

    # S3
    bucket: str                          # bucket name
    key_s3: str                          # piezas/{id_pieza}/{id_render_set}/{variante}.jpg
    # Image metadata
    created_at: datetime = Field(
    sa_column=Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
)


    # Relationships
    render_set: "RenderSet" = Relationship(back_populates="imagenes")
    label: Optional["Label"] = Relationship(back_populates="imagenes")
