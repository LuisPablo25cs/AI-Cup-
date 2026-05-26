from __future__ import annotations

from sqlmodel import SQLModel, Field, Relationship
import sqlalchemy.dialects.postgresql as pg
from sqlalchemy import Column as SAColumn, DateTime, ForeignKey, UniqueConstraint

from uuid import UUID, uuid4
from datetime import datetime, timezone


class KitPiezaLink(SQLModel, table=True):
    __tablename__ = "kit_pieza_link"

    id: UUID = Field(sa_column=SAColumn(pg.UUID, primary_key=True, default=uuid4))

    kit_id: UUID = Field(
        sa_column=SAColumn(
            pg.UUID,
            ForeignKey("kit.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )
    pieza_id: UUID = Field(
        sa_column=SAColumn(
            pg.UUID,
            ForeignKey("pieza.id_pieza"),
            nullable=False,
            index=True,
        )
    )

    cantidad_requerida: int = Field(default=1, gt=0)
    pos_x: float | None = None
    pos_y: float | None = None
    ancho_cm: float | None = None
    alto_cm: float | None = None
    icono: str | None = None
    es_agrupacion: bool = False

    __table_args__ = (UniqueConstraint("kit_id", "pieza_id", name="uq_kit_pieza"),)

    kit: "Kit" = Relationship(back_populates="items")


class Kit(SQLModel, table=True):
    __tablename__ = "kit"

    id: UUID = Field(
        sa_column=SAColumn(pg.UUID, primary_key=True, unique=True, default=uuid4)
    )

    nombre: str
    descripcion: str | None = None
    activo: bool = True
    ancho_cm: float | None = None
    largo_cm: float | None = None
    imagen_url: str | None = None

    # Informational FK for MVP.
    vision_model_id: UUID | None = Field(
        default=None,
        sa_column=SAColumn(pg.UUID, ForeignKey("vision_model.id_model"), nullable=True),
    )

    created_at: datetime = Field(
        sa_column=SAColumn(
            DateTime(timezone=True),
            default=lambda: datetime.now(timezone.utc),
        )
    )

    items: list[KitPiezaLink] = Relationship(
        back_populates="kit",
        sa_relationship_kwargs={
            "cascade": "all, delete-orphan",
            "lazy": "selectin",
        },
    )
