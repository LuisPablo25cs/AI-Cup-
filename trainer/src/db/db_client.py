from sqlmodel.ext.asyncio.session import AsyncSession
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select
from uuid import UUID
from dataclasses import dataclass
from typing import List, Optional
from datetime import datetime, timezone

from .config import config
from .models import Pieza, RenderSet, Label, Imagen, VisionModel

@dataclass(frozen=True)
class TrainingSample:
    image_key: str
    label_key: str
    variante: str
    render_set_id: str

class DBClient:
    def __init__(self):
        self.engine = create_async_engine(
            config.ASYNC_DATABASE_URL,
            echo=False,
            future=True,
            pool_size=10,
            max_overflow=20
        )
        self.async_session_maker = sessionmaker(
            self.engine, class_=AsyncSession, expire_on_commit=False
        )

    async def get_piece_name(self, piece_id: UUID) -> str:
        async with self.async_session_maker() as session:
            result = await session.execute(
                select(Pieza.nombre).where(Pieza.id_pieza == piece_id)
            )
            name = result.scalar_one_or_none()
            if not name:
                raise ValueError(f"Pieza with ID {piece_id} not found in database.")
            return name

    async def get_training_samples(self, piece_id: UUID) -> List[TrainingSample]:
        """
        Queries all RenderSets for the given piece_id that have a completed label.
        Fetches every BagVariant image inside those RenderSets.
        """
        async with self.async_session_maker() as session:
            query = (
                select(Imagen.key_s3, Label.key_s3, Imagen.variante, RenderSet.id_render_set)
                .join(RenderSet, Imagen.id_render_set == RenderSet.id_render_set)
                .join(Label, RenderSet.id_render_set == Label.id_render_set)
                .where(RenderSet.id_pieza == piece_id)
            )
            result = await session.execute(query)
            rows = result.all()
            
            return [
                TrainingSample(
                    image_key=row[0],
                    label_key=row[1],
                    variante=row[2].value if hasattr(row[2], 'value') else str(row[2]),
                    render_set_id=str(row[3])
                )
                for row in rows
            ]

    async def update_model_status(self, model_id: UUID, status: str, s3_key: Optional[str] = None) -> None:
        async with self.async_session_maker() as session:
            result = await session.execute(
                select(VisionModel).where(VisionModel.id_model == model_id)
            )
            model = result.scalar_one_or_none()
            if not model:
                raise ValueError(f"VisionModel with ID {model_id} not found in database.")
            
            model.estado = status
            if status in ["COMPLETED", "FAILED"]:
                model.completed_at = datetime.now(timezone.utc)
            if s3_key:
                model.key_s3_weights = s3_key
                
            await session.commit()

    async def close(self) -> None:
        await self.engine.dispose()