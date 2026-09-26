from __future__ import annotations
from pydantic import BaseModel, Field, ConfigDict, model_validator
from datetime import date as dt_date, time as dt_time, datetime as dt_datetime, timezone
from zoneinfo import ZoneInfo
from typing import Optional, List
import hashlib
import json


def normalize_to_utc(dt_or_date, t_val=None, tz_str="UTC") -> dt_datetime:
    """Convert local date/time or datetime to UTC-aware datetime."""
    try:
        zi = ZoneInfo(tz_str)
    except Exception:
        zi = timezone.utc

    if isinstance(dt_or_date, dt_datetime):
        if dt_or_date.tzinfo is None:
            localized = dt_or_date.replace(tzinfo=zi)
        else:
            localized = dt_or_date
        return localized.astimezone(timezone.utc)
    elif isinstance(dt_or_date, dt_date) and t_val is not None:
        naive = dt_datetime.combine(dt_or_date, t_val)
        localized = naive.replace(tzinfo=zi)
        return localized.astimezone(timezone.utc)
    else:
        raise ValueError("Invalid date/time inputs for normalization")


class TableResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    capacity: int
    timezone: str


class ReservationCreate(BaseModel):
    table_id: Optional[int] = None
    guest_name: str
    guest_email: Optional[str] = None
    party_size: int = Field(default=2, ge=1)
    date: Optional[dt_date] = None
    start_time: Optional[dt_time] = None
    end_time: Optional[dt_time] = None
    timezone: str = "UTC"
    start_at: Optional[dt_datetime] = None
    end_at: Optional[dt_datetime] = None
    idempotency_key: Optional[str] = None

    @model_validator(mode="after")
    def validate_and_normalize(self):
        # Resolve start_at
        if self.start_at is not None:
            self.start_at = normalize_to_utc(self.start_at, tz_str=self.timezone)
        elif self.date is not None and self.start_time is not None:
            self.start_at = normalize_to_utc(self.date, self.start_time, tz_str=self.timezone)
        else:
            raise ValueError("Must provide either start_at or (date, start_time)")

        # Resolve end_at
        if self.end_at is not None:
            self.end_at = normalize_to_utc(self.end_at, tz_str=self.timezone)
        elif self.date is not None and self.end_time is not None:
            self.end_at = normalize_to_utc(self.date, self.end_time, tz_str=self.timezone)
        else:
            raise ValueError("Must provide either end_at or (date, end_time)")

        if self.start_at >= self.end_at:
            raise ValueError("start_time must be strictly before end_time")

        return self

    def compute_payload_hash(self) -> str:
        """Deterministic hash of core reservation parameters."""
        data = {
            "table_id": self.table_id,
            "guest_name": self.guest_name,
            "party_size": self.party_size,
            "start_at": self.start_at.isoformat(),
            "end_at": self.end_at.isoformat(),
        }
        raw = json.dumps(data, sort_keys=True)
        return hashlib.sha256(raw.encode()).hexdigest()


class ReservationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    table_id: int
    guest_name: str
    guest_email: Optional[str] = None
    party_size: int = 2
    start_at: dt_datetime
    end_at: dt_datetime
    requested_timezone: str = "UTC"
    local_start: Optional[str] = None
    local_end: Optional[str] = None
    idempotency_key: Optional[str] = None

    @model_validator(mode="after")
    def populate_local_times(self):
        try:
            zi = ZoneInfo(self.requested_timezone)
            self.local_start = self.start_at.astimezone(zi).isoformat()
            self.local_end = self.end_at.astimezone(zi).isoformat()
        except Exception:
            self.local_start = self.start_at.isoformat()
            self.local_end = self.end_at.isoformat()
        return self


class WaitlistCreate(BaseModel):
    guest_name: str
    guest_email: Optional[str] = None
    party_size: int = Field(default=2, ge=1)
    date: Optional[dt_date] = None
    start_time: Optional[dt_time] = None
    end_time: Optional[dt_time] = None
    timezone: str = "UTC"
    start_at: Optional[dt_datetime] = None
    end_at: Optional[dt_datetime] = None

    @model_validator(mode="after")
    def validate_and_normalize(self):
        if self.start_at is not None:
            self.start_at = normalize_to_utc(self.start_at, tz_str=self.timezone)
        elif self.date is not None and self.start_time is not None:
            self.start_at = normalize_to_utc(self.date, self.start_time, tz_str=self.timezone)
        else:
            raise ValueError("Must provide either start_at or (date, start_time)")

        if self.end_at is not None:
            self.end_at = normalize_to_utc(self.end_at, tz_str=self.timezone)
        elif self.date is not None and self.end_time is not None:
            self.end_at = normalize_to_utc(self.date, self.end_time, tz_str=self.timezone)
        else:
            raise ValueError("Must provide either end_at or (date, end_time)")

        if self.start_at >= self.end_at:
            raise ValueError("start_time must be strictly before end_time")

        return self


class WaitlistResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    guest_name: str
    guest_email: Optional[str] = None
    party_size: int = 2
    start_at: dt_datetime
    end_at: dt_datetime
    requested_timezone: str = "UTC"
    status: str = "waiting"
    queue_position: Optional[int] = None
    promoted_reservation_id: Optional[int] = None


class CancellationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    cancelled_reservation_id: int
    promoted_waitlist_entry_id: Optional[int] = None
    promoted_reservation: Optional[ReservationResponse] = None
    message: str


class AvailabilityResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    table_id: int
    capacity: int
    available: bool
    query_start_utc: dt_datetime
    query_end_utc: dt_datetime
    conflicting_reservations: int
