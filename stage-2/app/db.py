from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from sqlalchemy import Column, Integer, String, DateTime, text, func
import os

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://user:pass@db:5432/tablekeeper_stage2")

engine = create_async_engine(DATABASE_URL, echo=False, pool_pre_ping=True)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class Table(Base):
    __tablename__ = "tables"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    capacity = Column(Integer, nullable=False)
    timezone = Column(String, nullable=False, default="UTC")


class Reservation(Base):
    __tablename__ = "reservations"
    id = Column(Integer, primary_key=True, autoincrement=True)
    idempotency_key = Column(String, index=True, nullable=True)
    payload_hash = Column(String, nullable=True)
    table_id = Column(Integer, nullable=False)
    guest_name = Column(String, nullable=False)
    guest_email = Column(String, nullable=True)
    start_at = Column(DateTime(timezone=True), nullable=False, index=True)
    end_at = Column(DateTime(timezone=True), nullable=False, index=True)
    requested_timezone = Column(String, nullable=False, default="UTC")
    created_at = Column(DateTime(timezone=True), server_default=func.now())


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text("""
            INSERT INTO tables (id, name, capacity, timezone)
            VALUES (1,'Table 1',4,'America/New_York'),
                   (2,'Table 2',2,'America/New_York'),
                   (3,'Table 3',6,'America/New_York'),
                   (4,'Table 4',4,'America/New_York'),
                   (5,'Table 5',8,'America/New_York')
            ON CONFLICT DO NOTHING
        """))


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session
