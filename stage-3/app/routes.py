from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text, func
from datetime import date as dt_date, time as dt_time, datetime as dt_datetime
from typing import List, Optional

from db import get_db, Reservation, Table, WaitlistEntry
from schemas import (
    ReservationCreate,
    ReservationResponse,
    WaitlistCreate,
    WaitlistResponse,
    CancellationResponse,
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
    """Count overlapping reservations for a table across UTC timestamps."""
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
    result = await db.execute(select(Table).order_by(Table.id.asc()))
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
            if existing.payload_hash == current_hash:
                return existing
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Idempotency key collision: key already used with different parameters",
            )

    async with db.begin_nested():
        chosen_table_id = payload.table_id

        if chosen_table_id is not None:
            # Table specified: verify table and capacity
            lock_query = text("SELECT id, capacity FROM tables WHERE id = :table_id FOR UPDATE")
            table_result = (await db.execute(lock_query, {"table_id": chosen_table_id})).mappings().one_or_none()
            if not table_result:
                raise HTTPException(status_code=404, detail=f"Table {chosen_table_id} does not exist")

            if table_result["capacity"] < payload.party_size:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Party size {payload.party_size} exceeds table capacity {table_result['capacity']}",
                )

            count = await check_overlap(
                db,
                table_id=chosen_table_id,
                start_at=payload.start_at,
                end_at=payload.end_at,
            )
            if count > 0:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Table {chosen_table_id} is already booked for that time slot",
                )
        else:
            # Auto-assign best-fit table (lowest capacity >= party_size)
            candidate_query = text("""
                SELECT id, capacity FROM tables
                WHERE capacity >= :party_size
                ORDER BY capacity ASC, id ASC
                FOR UPDATE
            """)
            candidates = (await db.execute(candidate_query, {"party_size": payload.party_size})).mappings().all()
            if not candidates:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"No tables exist that can accommodate party size {payload.party_size}",
                )

            selected = None
            for cand in candidates:
                cand_id = cand["id"]
                count = await check_overlap(
                    db,
                    table_id=cand_id,
                    start_at=payload.start_at,
                    end_at=payload.end_at,
                )
                if count == 0:
                    selected = cand_id
                    break

            if selected is None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="All eligible tables for this party size are fully booked. Please join waitlist.",
                )
            chosen_table_id = selected

        reservation = Reservation(
            table_id=chosen_table_id,
            guest_name=payload.guest_name,
            guest_email=payload.guest_email,
            party_size=payload.party_size,
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


@router.delete("/reservations/{reservation_id}", response_model=CancellationResponse)
async def cancel_reservation(reservation_id: int, db: AsyncSession = Depends(get_db)):
    """
    Cancels a reservation and atomically checks the waitlist to auto-promote
    the earliest eligible party into the vacated table.
    """
    async with db.begin():
        # Lock reservation
        res = await db.execute(
            select(Reservation).where(Reservation.id == reservation_id).with_for_update()
        )
        reservation = res.scalar_one_or_none()
        if not reservation:
            raise HTTPException(status_code=404, detail="Reservation not found")

        table_id = reservation.table_id
        start_at = reservation.start_at
        end_at = reservation.end_at

        # Lock table
        tbl_res = await db.execute(
            select(Table).where(Table.id == table_id).with_for_update()
        )
        table = tbl_res.scalar_one_or_none()
        table_capacity = table.capacity if table else 0

        # Remove confirmed reservation
        await db.delete(reservation)

        # Atomic Auto-Promotion: search for earliest waiting guest
        wl_query = text("""
            SELECT id, guest_name, guest_email, party_size, start_at, end_at, requested_timezone
            FROM waitlist
            WHERE status = 'waiting'
              AND party_size <= :table_capacity
              AND start_at < :end_at
              AND end_at > :start_at
            ORDER BY created_at ASC
            LIMIT 1
            FOR UPDATE
        """)
        wl_candidate = (await db.execute(wl_query, {
            "table_capacity": table_capacity,
            "start_at": start_at,
            "end_at": end_at,
        })).mappings().one_or_none()

        promoted_res = None
        promoted_wl_id = None

        if wl_candidate:
            promoted_wl_id = wl_candidate["id"]
            # Create promoted reservation
            promoted_res = Reservation(
                table_id=table_id,
                guest_name=wl_candidate["guest_name"],
                guest_email=wl_candidate["guest_email"],
                party_size=wl_candidate["party_size"],
                start_at=wl_candidate["start_at"],
                end_at=wl_candidate["end_at"],
                requested_timezone=wl_candidate["requested_timezone"],
                idempotency_key=f"promoted-from-wl-{promoted_wl_id}",
                payload_hash="promoted",
            )
            db.add(promoted_res)
            await db.flush()

            # Update waitlist entry status
            await db.execute(
                text("UPDATE waitlist SET status = 'promoted', promoted_reservation_id = :res_id WHERE id = :wl_id"),
                {"res_id": promoted_res.id, "wl_id": promoted_wl_id}
            )

    if promoted_res:
        promoted_response = ReservationResponse(
            id=promoted_res.id,
            table_id=promoted_res.table_id,
            guest_name=promoted_res.guest_name,
            guest_email=promoted_res.guest_email,
            party_size=promoted_res.party_size,
            start_at=promoted_res.start_at,
            end_at=promoted_res.end_at,
            requested_timezone=promoted_res.requested_timezone,
            idempotency_key=promoted_res.idempotency_key,
        )
        return CancellationResponse(
            cancelled_reservation_id=reservation_id,
            promoted_waitlist_entry_id=promoted_wl_id,
            promoted_reservation=promoted_response,
            message=f"Reservation {reservation_id} cancelled. Waitlisted party '{promoted_res.guest_name}' automatically promoted to Table {table_id}!",
        )

    return CancellationResponse(
        cancelled_reservation_id=reservation_id,
        message=f"Reservation {reservation_id} cancelled successfully.",
    )


@router.post("/waitlist", response_model=WaitlistResponse, status_code=status.HTTP_201_CREATED)
async def join_waitlist(
    payload: WaitlistCreate,
    db: AsyncSession = Depends(get_db),
):
    entry = WaitlistEntry(
        guest_name=payload.guest_name,
        guest_email=payload.guest_email,
        party_size=payload.party_size,
        start_at=payload.start_at,
        end_at=payload.end_at,
        requested_timezone=payload.timezone,
        status="waiting",
    )
    db.add(entry)
    await db.commit()
    await db.refresh(entry)

    # Compute queue position
    q_pos = await db.execute(
        text("SELECT COUNT(*) FROM waitlist WHERE status = 'waiting' AND created_at <= :created_at"),
        {"created_at": entry.created_at}
    )
    pos = q_pos.scalar() or 1

    return WaitlistResponse(
        id=entry.id,
        guest_name=entry.guest_name,
        guest_email=entry.guest_email,
        party_size=entry.party_size,
        start_at=entry.start_at,
        end_at=entry.end_at,
        requested_timezone=entry.requested_timezone,
        status=entry.status,
        queue_position=pos,
        promoted_reservation_id=entry.promoted_reservation_id,
    )


@router.get("/waitlist", response_model=List[WaitlistResponse])
async def list_waitlist(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(WaitlistEntry).order_by(WaitlistEntry.created_at.asc()))
    entries = result.scalars().all()
    out = []
    for idx, e in enumerate(entries, 1):
        pos = idx if e.status == "waiting" else None
        out.append(WaitlistResponse(
            id=e.id,
            guest_name=e.guest_name,
            guest_email=e.guest_email,
            party_size=e.party_size,
            start_at=e.start_at,
            end_at=e.end_at,
            requested_timezone=e.requested_timezone,
            status=e.status,
            queue_position=pos,
            promoted_reservation_id=e.promoted_reservation_id,
        ))
    return out


@router.get("/waitlist/{waitlist_id}", response_model=WaitlistResponse)
async def get_waitlist_entry(waitlist_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(WaitlistEntry).where(WaitlistEntry.id == waitlist_id))
    entry = result.scalar_one_or_none()
    if not entry:
        raise HTTPException(status_code=404, detail="Waitlist entry not found")

    pos = None
    if entry.status == "waiting":
        q_pos = await db.execute(
            text("SELECT COUNT(*) FROM waitlist WHERE status = 'waiting' AND created_at <= :created_at"),
            {"created_at": entry.created_at}
        )
        pos = q_pos.scalar()

    return WaitlistResponse(
        id=entry.id,
        guest_name=entry.guest_name,
        guest_email=entry.guest_email,
        party_size=entry.party_size,
        start_at=entry.start_at,
        end_at=entry.end_at,
        requested_timezone=entry.requested_timezone,
        status=entry.status,
        queue_position=pos,
        promoted_reservation_id=entry.promoted_reservation_id,
    )


@router.delete("/waitlist/{waitlist_id}", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_waitlist(waitlist_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(WaitlistEntry).where(WaitlistEntry.id == waitlist_id))
    entry = result.scalar_one_or_none()
    if not entry:
        raise HTTPException(status_code=404, detail="Waitlist entry not found")
    entry.status = "cancelled"
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
    tbl_res = await db.execute(select(Table).where(Table.id == table_id))
    table = tbl_res.scalar_one_or_none()
    if not table:
        raise HTTPException(status_code=404, detail="Table not found")

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
        capacity=table.capacity,
        available=(count == 0),
        query_start_utc=utc_start,
        query_end_utc=utc_end,
        conflicting_reservations=count,
    )


@router.post("/testing/reset")
async def reset_database(db: AsyncSession = Depends(get_db)):
    """Reset reservations and waitlist for clean testing."""
    await db.execute(text("TRUNCATE reservations, waitlist RESTART IDENTITY CASCADE"))
    await db.commit()
    return {"status": "reset", "stage": 3}
