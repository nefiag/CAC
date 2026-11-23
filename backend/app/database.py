import os
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://localhost:5432/coxiaoac",
)

connect_args = (
    {"statement_cache_size": 0, "prepared_statement_cache_size": 0}
    if DATABASE_URL.startswith("postgresql") else {}
)
engine = create_async_engine(DATABASE_URL, connect_args=connect_args, pool_pre_ping=True, echo=False, future=True)
AsyncSessionLocal = async_sessionmaker(
    bind=engine, class_=AsyncSession, expire_on_commit=False
)


class Base(DeclarativeBase):
    pass


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session
