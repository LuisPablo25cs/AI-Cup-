from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlmodel.ext.asyncio.session import AsyncSession  
from sqlmodel import SQLModel
import os
from .models.pieza import Pieza
from .models.imagen import Imagen
from .models.render_set import RenderSet
from .models.vision_model import VisionModel
from .models.label import Label
from .models.kit import Kit, KitPiezaLink

#Database settings
DATABASE_URL = os.getenv("DATABASE_URL")
ASYNC_DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://")

#Create Engine
asyncEngine = create_async_engine(url=ASYNC_DATABASE_URL, 
                                  echo = False #Change to True for debugging
                                  )  

#Replaces the syncronous sessions in the endpoints
AsyncSessionLocal = async_sessionmaker(asyncEngine, class_=AsyncSession, expire_on_commit=False)


async def test_connection():
    print("Testing database connection...")
    try:
        async with asyncEngine.connect() as conn:
            print("Nice! Connection successful")
    except Exception as e:
        print(f"NON! Connection failed: {e}")
        raise


#Create Database Tables
async def init_db():
    async with asyncEngine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)



async def get_session():
    async with AsyncSessionLocal() as session:
        yield session

    #yield devuelve el resultado hasta el momento y continúa con el siguiente paso.
