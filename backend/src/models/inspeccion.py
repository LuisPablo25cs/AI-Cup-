from datetime import datetime, timezone
from uuid import UUID, uuid4

import sqlalchemy.dialects.postgresql as pg
from sqlalchemy import Column as SAColumn, DateTime, ForeignKey
from sqlmodel import Field, Relationship, SQLModel


class Deteccion(SQLModel, table=True):
    __tablename__ = "deteccion"

    id: UUID = Field(sa_column=SAColumn(pg.UUID, primary_key=True, default=uuid4))

    inspeccion_id: UUID = Field(
        sa_column=SAColumn(
            pg.UUID,
            ForeignKey("inspeccion.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )
    pieza_id: UUID | None = Field(
        default=None,
        sa_column=SAColumn(
            pg.UUID,
            ForeignKey("pieza.id_pieza"),
            nullable=True,
        ),
    )

    # Snapshot of the strategy output.
    pieza_nombre: str
    encontrado: bool = True
    confianza: float = 0.0
    posicion_x_pct: float | None = None
    posicion_y_pct: float | None = None
    width_pct: float | None = None
    height_pct: float | None = None
    estado: str | None = None
    corregido_por_operador: bool = False

    inspeccion: "Inspeccion" = Relationship(back_populates="detecciones")


class Inspeccion(SQLModel, table=True):
    __tablename__ = "inspeccion"

    id: UUID = Field(
        sa_column=SAColumn(pg.UUID, primary_key=True, unique=True, default=uuid4)
    )

    kit_id: UUID = Field(
        sa_column=SAColumn(
            pg.UUID,
            ForeignKey("kit.id"),
            nullable=False,
            index=True,
        )
    )
    vision_model_id: UUID | None = Field(
        default=None,
        sa_column=SAColumn(
            pg.UUID,
            ForeignKey("vision_model.id_model"),
            nullable=True,
        ),
    )
    kit_nombre: str
    fecha: datetime = Field(
        sa_column=SAColumn(
            DateTime(timezone=True),
            default=lambda: datetime.now(timezone.utc),
            index=True,
        )
    )
    resultado_general: str = Field(index=True)  # correcto | anomalia | error
    similitud: float = 0.0
    tiempo_procesamiento: float = 0.0
    operador: str | None = Field(default=None, index=True)
    imagen_s3_key: str | None = None
    created_at: datetime = Field(
        sa_column=SAColumn(
            DateTime(timezone=True),
            default=lambda: datetime.now(timezone.utc),
        )
    )

    detecciones: list[Deteccion] = Relationship(
        back_populates="inspeccion",
        sa_relationship_kwargs={
            "cascade": "all, delete-orphan",
            "lazy": "selectin",
        },
    )
