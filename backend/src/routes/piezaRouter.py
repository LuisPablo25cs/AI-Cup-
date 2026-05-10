from fastapi import APIRouter, Depends, HTTPException
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import select
from src.db import get_session
from src.models.pieza import Pieza
from uuid import UUID
from datetime import datetime, timezone
from pydantic import BaseModel

router = APIRouter(prefix="/piezas", tags=["Piezas"])


# ── Schemas ────────────────────────────────────────────────────────────────────

class PiezaCreate(BaseModel):
    nombre: str
    descripcion: str | None = None
    cantidad_estimada: int = 1


class PiezaUpdate(BaseModel):
    nombre: str | None = None
    descripcion: str | None = None
    cantidad_estimada: int | None = None
    activo: bool | None = None


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.post("/", response_model=Pieza)
async def crear_pieza(
    data: PiezaCreate,
    session: AsyncSession = Depends(get_session)
):
    pieza = Pieza(**data.model_dump())
    session.add(pieza)
    await session.commit()
    await session.refresh(pieza)
    return pieza


@router.get("/", response_model=list[Pieza])
async def obtener_piezas(
    session: AsyncSession = Depends(get_session)
):
    result = await session.exec(select(Pieza))
    return result.all()


@router.get("/{id_pieza}", response_model=Pieza)
async def obtener_pieza(
    id_pieza: UUID,
    session: AsyncSession = Depends(get_session)
):
    pieza = await session.get(Pieza, id_pieza)
    if not pieza:
        raise HTTPException(status_code=404, detail="Pieza no encontrada")
    return pieza


@router.patch("/{id_pieza}", response_model=Pieza)
async def actualizar_pieza(
    id_pieza: UUID,
    data: PiezaUpdate,
    session: AsyncSession = Depends(get_session)
):
    pieza = await session.get(Pieza, id_pieza)
    if not pieza:
        raise HTTPException(status_code=404, detail="Pieza no encontrada")

    campos = data.model_dump(exclude_unset=True)  # solo campos enviados
    for campo, valor in campos.items():
        setattr(pieza, campo, valor)

    pieza.edited_at = datetime.now(timezone.utc)
    session.add(pieza)
    await session.commit()
    await session.refresh(pieza)
    return pieza


@router.delete("/{id_pieza}")
async def eliminar_pieza(
    id_pieza: UUID,
    session: AsyncSession = Depends(get_session)
):
    pieza = await session.get(Pieza, id_pieza)
    if not pieza:
        raise HTTPException(status_code=404, detail="Pieza no encontrada")

    await session.delete(pieza)
    await session.commit()
    return {"message": f"Pieza {id_pieza} eliminada"}