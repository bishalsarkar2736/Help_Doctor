from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker,create_async_engine

from app.config import get_settings
from app.db.base import Base


settings = get_settings()


engine = create_async_engine(
    settings.database_url,
    echo = settings.DEBUG,
    pool_size = 10,
    max_overflow = 20,
    pool_pre_ping = True
)


AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False
)


#Dependency for FastAPI
async def get_db():
    async with AsyncSessionLocal() as session:
       
        yield session
       

