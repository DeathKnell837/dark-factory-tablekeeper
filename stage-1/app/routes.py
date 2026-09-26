from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, text
from sqlalchemy.exc import IntegrityError
from datetime import date, time
from typing import List, Optional

from db import get_db, Reservation, Table
from schemas import ReservationCreate, ReservationResponse, TableResponse, AvailabilityResponse

router = APIRouter()


async def check_overlap(
    session: AsyncSession,
    table_id: int,
    date_: date,
    start_time: time,
    end_time: time,
    exclude_id: Optional[int] = None,
) -> int:
    """
    Count overlapping reservations for a table on a given date/time range.
    """
    query = text("""
        SELECT COUNT(*) FROM reservations
        WHERE table_id = :table_id
          AND date = :date
          AND start_time < :end_time
          AND end_time > :start_time
          AND (CAST(:exclude_id AS INTEGER) IS NULL OR id != CAST(:exclude_id AS INTEGER))
    """)

    result = await session.execute(query, {
        "table_id": table_id,
        "date": date_,
        "start_time": start_time,
        "end_time": end_time,
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
    # Idempotency: if key exists, return existing reservation
    if payload.idempotency_key:
        existing = await db.execute(
            select(Reservation).where(Reservation.idempotency_key == payload.idempotency_key)
        )
        existing = existing.scalar_one_or_none()
        if existing:
            return existing

    # Validate time range
    if payload.start_time >= payload.end_time:
        raise HTTPException(status_code=400, detail="start_time must be before end_time")

    async with db.begin_nested():
        # Lock the table row exclusively for the duration of this transaction
        lock_query = text("SELECT id FROM tables WHERE id = :table_id FOR UPDATE")
        table_result = await db.execute(lock_query, {"table_id": payload.table_id})
        if not table_result.scalar():
            raise HTTPException(status_code=404, detail=f"Table {payload.table_id} does not exist")

        # Now check for overlapping reservations under exclusive lock
        count = await check_overlap(
            db,
            table_id=payload.table_id,
            date_=payload.date,
            start_time=payload.start_time,
            end_time=payload.end_time,
        )
        if count > 0:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Table {payload.table_id} is already booked for that time slot",
            )

        reservation = Reservation(
            table_id=payload.table_id,
            guest_name=payload.guest_name,
            guest_email=payload.guest_email,
            date=payload.date,
            start_time=payload.start_time,
            end_time=payload.end_time,
            timezone=payload.timezone,
            idempotency_key=payload.idempotency_key,
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
    date: date,
    start_time: time,
    end_time: time,
    db: AsyncSession = Depends(get_db),
):
    count = await check_overlap(db, table_id, date, start_time, end_time)
    return AvailabilityResponse(
        table_id=table_id,
        date=date,
        available=(count == 0),
        conflicting_reservations=count,
    )
