import asyncio
import pytest
import httpx

BASE_URL = "http://localhost:8000"
TEST_DATE = "2026-10-15"


@pytest.mark.asyncio
async def test_health():
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        r = await client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_create_reservation():
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        r = await client.post("/reservations", json={
            "table_id": 1,
            "guest_name": "Alice",
            "date": TEST_DATE,
            "start_time": "18:00:00",
            "end_time": "20:00:00",
            "timezone": "UTC"
        })
    assert r.status_code == 201
    assert r.json()["guest_name"] == "Alice"


@pytest.mark.asyncio
async def test_no_double_booking_sequential():
    """Second booking for same overlapping slot must return 409."""
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        r1 = await client.post("/reservations", json={
            "table_id": 2, "guest_name": "Bob",
            "date": TEST_DATE, "start_time": "12:00:00", "end_time": "14:00:00"
        })
        assert r1.status_code == 201
        r2 = await client.post("/reservations", json={
            "table_id": 2, "guest_name": "Charlie",
            "date": TEST_DATE, "start_time": "13:00:00", "end_time": "15:00:00"
        })
        assert r2.status_code == 409, f"Expected 409, got {r2.status_code}"


@pytest.mark.asyncio
async def test_no_double_booking_concurrent():
    """
    THE HARD CONSTRAINT TEST.
    50 concurrent requests for the same table/slot.
    Exactly 1 must succeed (201). The other 49 must fail (409).
    """
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        tasks = [
            client.post("/reservations", json={
                "table_id": 3, "guest_name": f"Guest-{i}",
                "date": TEST_DATE, "start_time": "19:00:00", "end_time": "21:00:00"
            })
            for i in range(50)
        ]
        results = await asyncio.gather(*tasks)

    successes = [r for r in results if r.status_code == 201]
    assert len(successes) == 1, (
        f"DOUBLE BOOKING: {len(successes)} reservations created for same slot! Expected exactly 1."
    )


@pytest.mark.asyncio
async def test_idempotency_key():
    """Same idempotency key sent twice must return same reservation ID."""
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        payload = {
            "table_id": 4, "guest_name": "Dave",
            "date": TEST_DATE, "start_time": "10:00:00", "end_time": "11:00:00",
            "idempotency_key": "idem-test-001"
        }
        r1 = await client.post("/reservations", json=payload)
        r2 = await client.post("/reservations", json=payload)
    assert r1.status_code == 201
    assert r2.status_code == 201
    assert r1.json()["id"] == r2.json()["id"], "Must return same reservation"


@pytest.mark.asyncio
async def test_availability_check():
    """Availability endpoint must reflect actual bookings."""
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        await client.post("/reservations", json={
            "table_id": 5, "guest_name": "Eve",
            "date": TEST_DATE, "start_time": "14:00:00", "end_time": "16:00:00"
        })
        r = await client.get("/tables/5/availability", params={
            "date": TEST_DATE, "start_time": "14:30:00", "end_time": "15:30:00"
        })
        assert r.json()["available"] is False

        r2 = await client.get("/tables/5/availability", params={
            "date": TEST_DATE, "start_time": "16:00:00", "end_time": "18:00:00"
        })
        assert r2.json()["available"] is True


@pytest.mark.asyncio
async def test_cancel_reservation():
    """Cancel a reservation - slot must become available again."""
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        r = await client.post("/reservations", json={
            "table_id": 1, "guest_name": "Frank",
            "date": "2026-11-01", "start_time": "09:00:00", "end_time": "10:00:00"
        })
        assert r.status_code == 201
        res_id = r.json()["id"]
        del_r = await client.delete(f"/reservations/{res_id}")
        assert del_r.status_code == 204
        avail = await client.get("/tables/1/availability", params={
            "date": "2026-11-01", "start_time": "09:00:00", "end_time": "10:00:00"
        })
        assert avail.json()["available"] is True
