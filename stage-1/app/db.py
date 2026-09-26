from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from sqlalchemy import Column, Integer, String, Date, Time, DateTime, func
import os

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://user:pass@db:5432/tablekeeper")

engine = create_async_engine(DATABASE_URL, echo=False, pool_pre_ping=True)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class Table(Base):
    __tablename__ = "tables"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    capacity = Column(Integer, nullable=False)


class Reservation(Base):
    __tablename__ = "reservations"
    id = Column(Integer, primary_key=True, autoincrement=True)
    idempotency_key = Column(String, unique=True, nullable=True)
    table_id = Column(Integer, nullable=False)
    guest_name = Column(String, nullable=False)
    guest_email = Column(String, nullable=True)
    date = Column(Date, nullable=False)
    start_time = Column(Time, nullable=False)
    end_time = Column(Time, nullable=False)
    timezone = Column(String, nullable=False, default="UTC")
    created_at = Column(DateTime, server_default=func.now())


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        from sqlalchemy import text
        await conn.execute(text("""
            INSERT INTO tables (id, name, capacity)
            VALUES (1,'Table 1',4),(2,'Table 2',2),(3,'Table 3',6),
                   (4,'Table 4',4),(5,'Table 5',8)
            ON CONFLICT DO NOTHING
        """))


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session
