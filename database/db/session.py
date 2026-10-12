from typing import Any, AsyncGenerator

from sqlalchemy import Engine, create_engine
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from config import settings
from core.utils import BASE_DIR

if settings.DEBUG:
    SQLALCHEMY_ASYNC_DATABASE_URL = f"sqlite+aiosqlite:///{BASE_DIR}/db.sqlite"
    SQLALCHEMY_DATABASE_URL = f"sqlite:///{BASE_DIR}/db.sqlite"
else:
    SQLALCHEMY_ASYNC_DATABASE_URL = f"postgresql+asyncpg://{settings.DB_USER}:{settings.DB_PASS}@{settings.DB_HOST}:{settings.DB_PORT}/{settings.DB_NAME}"
    SQLALCHEMY_DATABASE_URL = f"postgresql://{settings.DB_USER}:{settings.DB_PASS}@{settings.DB_HOST}:{settings.DB_PORT}/{settings.DB_NAME}"

engine: Engine = create_engine(SQLALCHEMY_DATABASE_URL)

engine_async: AsyncEngine = create_async_engine(
    SQLALCHEMY_ASYNC_DATABASE_URL, echo=False
)
AsyncSessionLocal = async_sessionmaker(
    bind=engine_async,
    expire_on_commit=False,
    class_=AsyncSession,
)


async def get_async_db() -> AsyncGenerator[AsyncSession | Any, Any]:
    async with AsyncSessionLocal() as session:
        yield session
