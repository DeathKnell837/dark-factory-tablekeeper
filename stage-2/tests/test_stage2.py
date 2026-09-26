import asyncio
import pytest
import httpx
from datetime import datetime, timezone

BASE_URL = "http://localhost:8000"


@pytest.mark.asyncio
async def test_health():
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        r = await client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    assert r.json()["stage"] == 2


@pytest.mark.asyncio
async def test_timezone_collision_cross_zones():
    """
    CRITICAL TIMEZONE TEST:
    Guest 1 books Table 1 in America/New_York: 2026-10-15 19:00 - 21:00 EDT (23:00 - 01:00 UTC next day).
    Guest 2 attempts Table 1 in Asia/Tokyo: 2026-10-16 08:30 - 10:00 JST (23:30 - 01:00 UTC).
    Local dates and clock times look completely different, but in UTC they overlap.
    Second booking MUST return 409 Conflict.
    """
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        # Booking 1: New York
        r1 = await client.post("/reservations", json={
            "table_id": 1,
            "guest_name": "NY Guest",
            "date": "2026-10-15",
            "start_time": "19:00:00",
            "end_time": "21:00:00",
            "timezone": "America/New_York"
        })
        assert r1.status_code == 201
        res1 = r1.json()
        assert res1["requested_timezone"] == "America/New_York"

        # Booking 2: Tokyo (collides in UTC)
        r2 = await client.post("/reservations", json={
            "table_id": 1,
            "guest_name": "Tokyo Guest",
            "date": "2026-10-16",
            "start_time": "08:30:00",
            "end_time": "10:00:00",
            "timezone": "Asia/Tokyo"
        })
        assert r2.status_code == 409, f"Expected 409, got {r2.status_code}: {r2.text}"


@pytest.mark.asyncio
async def test_timezone_non_colliding_different_zones():
    """Two bookings in different timezones that do NOT collide in UTC."""
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        r1 = await client.post("/reservations", json={
            "table_id": 2,
            "guest_name": "London Guest",
            "date": "2026-11-20",
            "start_time": "12:00:00",
            "end_time": "14:00:00",
            "timezone": "Europe/London"
        })
        assert r1.status_code == 201

        # 4 hours later in UTC
        r2 = await client.post("/reservations", json={
            "table_id": 2,
            "guest_name": "LA Guest",
            "date": "2026-11-20",
            "start_time": "10:00:00",
            "end_time": "12:00:00",
            "timezone": "America/Los_Angeles" # 18:00 - 20:00 UTC
        })
        assert r2.status_code == 201


@pytest.mark.asyncio
async def test_concurrent_50_across_5_timezones():
    """
    50 concurrent requests targeting the same absolute slot across 5 timezones.
    Target slot: 2026-12-01 20:00:00 to 22:00:00 UTC.
    Exactly 1 request must succeed (201). The other 49 must fail (409).
    """
    tz_configs = [
        {"tz": "UTC", "d": "2026-12-01", "st": "20:00:00", "et": "22:00:00"},
        {"tz": "America/New_York", "d": "2026-12-01", "st": "15:00:00", "et": "17:00:00"}, # UTC-5
        {"tz": "Europe/Paris", "d": "2026-12-01", "st": "21:00:00", "et": "23:00:00"},      # UTC+1
        {"tz": "Asia/Tokyo", "d": "2026-12-02", "st": "05:00:00", "et": "07:00:00"},        # UTC+9
        {"tz": "Australia/Sydney", "d": "2026-12-02", "st": "07:00:00", "et": "09:00:00"},  # UTC+11
    ]

    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        tasks = []
        for i in range(50):
            cfg = tz_configs[i % len(tz_configs)]
            tasks.append(client.post("/reservations", json={
                "table_id": 3,
                "guest_name": f"Concurrent-{i}",
                "date": cfg["d"],
                "start_time": cfg["st"],
                "end_time": cfg["et"],
                "timezone": cfg["tz"]
            }))
        results = await asyncio.gather(*tasks)

    successes = [r for r in results if r.status_code == 201]
    assert len(successes) == 1, (
        f"CROSS-TIMEZONE DOUBLE BOOKING: {len(successes)} bookings created for same slot! Expected exactly 1."
    )


@pytest.mark.asyncio
async def test_idempotent_retry_identical():
    """Identical retries with same idempotency key must return the same reservation."""
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        payload = {
            "table_id": 4,
            "guest_name": "Retry User",
            "date": "2026-12-10",
            "start_time": "18:00:00",
            "end_time": "20:00:00",
            "timezone": "America/New_York",
            "idempotency_key": "stage2-retry-key-001"
        }
        r1 = await client.post("/reservations", json=payload)
        r2 = await client.post("/reservations", json=payload)

    assert r1.status_code == 201
    assert r2.status_code == 201
    assert r1.json()["id"] == r2.json()["id"]


@pytest.mark.asyncio
async def test_idempotent_retry_mismatched_payload():
    """Same idempotency key with conflicting parameters must return 422."""
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        key = "stage2-conflict-key-999"
        r1 = await client.post("/reservations", json={
            "table_id": 5,
            "guest_name": "Original User",
            "date": "2026-12-15",
            "start_time": "12:00:00",
            "end_time": "14:00:00",
            "timezone": "UTC",
            "idempotency_key": key
        })
        assert r1.status_code == 201

        # Second request with different time using the SAME key
        r2 = await client.post("/reservations", json={
            "table_id": 5,
            "guest_name": "Different User",
            "date": "2026-12-15",
            "start_time": "15:00:00",
            "end_time": "17:00:00",
            "timezone": "UTC",
            "idempotency_key": key
        })
        assert r2.status_code == 422, f"Expected 422, got {r2.status_code}"


@pytest.mark.asyncio
async def test_cross_timezone_availability():
    """Check availability across different timezones."""
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        # Book table 4 from 18:00 to 20:00 UTC on 2026-12-25
        await client.post("/reservations", json={
            "table_id": 4,
            "guest_name": "Holiday Guest",
            "date": "2026-12-25",
            "start_time": "18:00:00",
            "end_time": "20:00:00",
            "timezone": "UTC"
        })

        # Query in America/New_York (13:00 - 15:00 EDT = 18:00 - 20:00 UTC) -> should be unavailable
        r = await client.get("/tables/4/availability", params={
            "date": "2026-12-25",
            "start_time": "13:30:00",
            "end_time": "14:30:00",
            "timezone": "America/New_York"
        })
        assert r.status_code == 200
        assert r.json()["available"] is False

        # Query for slot after (21:00 UTC = 16:00 NY) -> should be available
        r2 = await client.get("/tables/4/availability", params={
            "date": "2026-12-25",
            "start_time": "16:00:00",
            "end_time": "18:00:00",
            "timezone": "America/New_York"
        })
        assert r2.status_code == 200
        assert r2.json()["available"] is True
