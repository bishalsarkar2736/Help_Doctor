import os
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker,create_async_engine
from app.config import get_settings
from opentelemetry.instrumentation.sqlalchemy import (
    SQLAlchemyInstrumentor,
)

settings = get_settings()
print("APP CONNECTING TO DB:", settings.POSTGRES_DB)


engine = create_async_engine(
    settings.database_url,
    echo = settings.DEBUG,
    # Per process — see the budget note on DB_POOL_SIZE in config.py.
    pool_size = settings.DB_POOL_SIZE,
    max_overflow = settings.DB_MAX_OVERFLOW,
    pool_pre_ping = True,
    pool_recycle=1800,
)

if os.getenv("TESTING") != "1":
    SQLAlchemyInstrumentor().instrument(
        engine=engine.sync_engine
    )


AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False
)


#Dependency for FastAPI
async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()   # ✅ commit here ONLY
        except Exception:
            await session.rollback()
            raise
       

