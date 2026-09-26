from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text
from datetime import date as dt_date, time as dt_time, datetime as dt_datetime
from typing import List, Optional

from db import get_db, Reservation, Table
from schemas import (
    ReservationCreate,
    ReservationResponse,
    TableResponse,
    AvailabilityResponse,
    normalize_to_utc,
)

router = APIRouter()


async def check_overlap(
    session: AsyncSession,
    table_id: int,
    start_at: dt_datetime,
    end_at: dt_datetime,
    exclude_id: Optional[int] = None,
) -> int:
    """
    Count overlapping reservations for a table across UTC timestamps.
    """
    query = text("""
        SELECT COUNT(*) FROM reservations
        WHERE table_id = :table_id
          AND start_at < :end_at
          AND end_at > :start_at
          AND (CAST(:exclude_id AS INTEGER) IS NULL OR id != CAST(:exclude_id AS INTEGER))
    """)

    result = await session.execute(query, {
        "table_id": table_id,
        "start_at": start_at,
        "end_at": end_at,
        "exclude_id": exclude_id,
    })
    return result.scalar()


@router.get("/tables", response_model=List[TableResponse])
async def list_tables(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Table))
    return result.scalars().all()


@router.post("/reservations", response_model=ReservationResponse, status_code=status.HTTP_201_CREATED)
async def create_reservation(
    payload: ReservationCreate,
    db: AsyncSession = Depends(get_db),
):
    current_hash = payload.compute_payload_hash()

    # Enhanced Idempotency handling
    if payload.idempotency_key:
        existing = await db.execute(
            select(Reservation).where(Reservation.idempotency_key == payload.idempotency_key)
        )
        existing = existing.scalar_one_or_none()
        if existing:
            # If payload matches, return original reservation
            if existing.payload_hash == current_hash:
                return existing
            # If same key used for different parameters, reject as unprocessable
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Idempotency key collision: key already used with different parameters",
            )

    async with db.begin_nested():
        # Acquire pessimistic exclusive lock on the table resource
        lock_query = text("SELECT id FROM tables WHERE id = :table_id FOR UPDATE")
        table_result = await db.execute(lock_query, {"table_id": payload.table_id})
        if not table_result.scalar():
            raise HTTPException(status_code=404, detail=f"Table {payload.table_id} does not exist")

        # Check for overlaps against normalized UTC timestamps
        count = await check_overlap(
            db,
            table_id=payload.table_id,
            start_at=payload.start_at,
            end_at=payload.end_at,
        )
        if count > 0:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Table {payload.table_id} is already booked for that absolute time slot",
            )

        reservation = Reservation(
            table_id=payload.table_id,
            guest_name=payload.guest_name,
            guest_email=payload.guest_email,
            start_at=payload.start_at,
            end_at=payload.end_at,
            requested_timezone=payload.timezone,
            idempotency_key=payload.idempotency_key,
            payload_hash=current_hash,
        )
        db.add(reservation)

    await db.commit()
    await db.refresh(reservation)
    return reservation


@router.get("/reservations/{reservation_id}", response_model=ReservationResponse)
async def get_reservation(reservation_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Reservation).where(Reservation.id == reservation_id))
    reservation = result.scalar_one_or_none()
    if not reservation:
        raise HTTPException(status_code=404, detail="Reservation not found")
    return reservation


@router.delete("/reservations/{reservation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_reservation(reservation_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Reservation).where(Reservation.id == reservation_id))
    reservation = result.scalar_one_or_none()
    if not reservation:
        raise HTTPException(status_code=404, detail="Reservation not found")
    await db.delete(reservation)
    await db.commit()


@router.get("/tables/{table_id}/availability", response_model=AvailabilityResponse)
async def check_availability(
    table_id: int,
    date: Optional[dt_date] = None,
    start_time: Optional[dt_time] = None,
    end_time: Optional[dt_time] = None,
    start_at: Optional[dt_datetime] = None,
    end_at: Optional[dt_datetime] = None,
    timezone: str = "UTC",
    db: AsyncSession = Depends(get_db),
):
    # Resolve start_at and end_at to UTC
    if start_at is not None and end_at is not None:
        utc_start = normalize_to_utc(start_at, tz_str=timezone)
        utc_end = normalize_to_utc(end_at, tz_str=timezone)
    elif date is not None and start_time is not None and end_time is not None:
        utc_start = normalize_to_utc(date, start_time, tz_str=timezone)
        utc_end = normalize_to_utc(date, end_time, tz_str=timezone)
    else:
        raise HTTPException(
            status_code=400,
            detail="Must provide either (start_at, end_at) or (date, start_time, end_time)",
        )

    count = await check_overlap(db, table_id, utc_start, utc_end)
    return AvailabilityResponse(
        table_id=table_id,
        available=(count == 0),
        query_start_utc=utc_start,
        query_end_utc=utc_end,
        conflicting_reservations=count,
    )
