from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from sqlalchemy import Column, Integer, String, DateTime, text, func
import os

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://user:pass@db:5432/tablekeeper_stage3")

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
    table_id = Column(Integer, nullable=False, index=True)
    guest_name = Column(String, nullable=False)
    guest_email = Column(String, nullable=True)
    party_size = Column(Integer, nullable=False, default=2)
    start_at = Column(DateTime(timezone=True), nullable=False, index=True)
    end_at = Column(DateTime(timezone=True), nullable=False, index=True)
    requested_timezone = Column(String, nullable=False, default="UTC")
    idempotency_key = Column(String, index=True, nullable=True)
    payload_hash = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class WaitlistEntry(Base):
    __tablename__ = "waitlist"
    id = Column(Integer, primary_key=True, autoincrement=True)
    guest_name = Column(String, nullable=False)
    guest_email = Column(String, nullable=True)
    party_size = Column(Integer, nullable=False, default=2)
    start_at = Column(DateTime(timezone=True), nullable=False, index=True)
    end_at = Column(DateTime(timezone=True), nullable=False, index=True)
    requested_timezone = Column(String, nullable=False, default="UTC")
    status = Column(String, nullable=False, default="waiting", index=True)  # waiting, promoted, cancelled
    promoted_reservation_id = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text("""
            INSERT INTO tables (id, name, capacity, timezone)
            VALUES (1,'Table 1 (2-Top)',2,'America/New_York'),
                   (2,'Table 2 (2-Top)',2,'America/New_York'),
                   (3,'Table 3 (4-Top)',4,'America/New_York'),
                   (4,'Table 4 (4-Top)',4,'America/New_York'),
                   (5,'Table 5 (6-Top)',6,'America/New_York'),
                   (6,'Table 6 (8-Top)',8,'America/New_York')
            ON CONFLICT DO NOTHING
        """))


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session
