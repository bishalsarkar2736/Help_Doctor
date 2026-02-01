from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from app.config import Settings

engine = create_async_engine(
    Settings.database_url,
    pool_pre_ping = True,
    echo = False
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    expire_on_commit=False
)