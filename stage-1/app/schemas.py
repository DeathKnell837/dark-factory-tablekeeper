from pydantic import BaseModel
from datetime import date, time
from typing import Optional


class ReservationCreate(BaseModel):
    table_id: int
    guest_name: str
    guest_email: Optional[str] = None
    date: date
    start_time: time
    end_time: time
    timezone: str = "UTC"
    idempotency_key: Optional[str] = None


class ReservationResponse(BaseModel):
    id: int
    table_id: int
    guest_name: str
    guest_email: Optional[str]
    date: date
    start_time: time
    end_time: time
    timezone: str
    idempotency_key: Optional[str]

    class Config:
        from_attributes = True


class TableResponse(BaseModel):
    id: int
    name: str
    capacity: int

    class Config:
        from_attributes = True


class AvailabilityResponse(BaseModel):
    table_id: int
    date: date
    available: bool
    conflicting_reservations: int
