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
            "start_time": "18:00",
            "end_time": "20:00",
            "timezone": "UTC"
        })
    assert r.status_code == 201
    data = r.json()
    assert data["table_id"] == 1
    assert data["guest_name"] == "Alice"


@pytest.mark.asyncio
async def test_no_double_booking_sequential():
    """Two sequential bookings for the same slot — second must fail with 409."""
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        r1 = await client.post("/reservations", json={
            "table_id": 2,
            "guest_name": "Bob",
            "date": TEST_DATE,
            "start_time": "12:00",
            "end_time": "14:00",
        })
        assert r1.status_code == 201

        r2 = await client.post("/reservations", json={
            "table_id": 2,
            "guest_name": "Charlie",
            "date": TEST_DATE,
            "start_time": "13:00",  # overlaps
            "end_time": "15:00",
        })
        assert r2.status_code == 409, f"Expected 409 conflict, got {r2.status_code}"


@pytest.mark.asyncio
async def test_no_double_booking_concurrent():
    """
    50 concurrent requests for the same table/slot.
    Exactly 1 must succeed (201). The rest must fail (409).
    This is the core hard constraint test.
    """
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        tasks = [
            client.post("/reservations", json={
                "table_id": 3,
                "guest_name": f"Guest-{i}",
                "date": TEST_DATE,
                "start_time": "19:00",
                "end_time": "21:00",
            })
            for i in range(50)
        ]
        results = await asyncio.gather(*tasks)

    successes = [r for r in results if r.status_code == 201]
    conflicts = [r for r in results if r.status_code == 409]

    assert len(successes) == 1, (
        f"DOUBLE BOOKING DETECTED: {len(successes)} reservations created for same slot! "
        f"Expected exactly 1."
    )
    assert len(conflicts) == 49, f"Expected 49 conflicts, got {len(conflicts)}"


@pytest.mark.asyncio
async def test_idempotency_key():
    """Same idempotency key sent twice — must return same reservation, not duplicate."""
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        payload = {
            "table_id": 4,
            "guest_name": "Dave",
            "date": TEST_DATE,
            "start_time": "10:00",
            "end_time": "11:00",
            "idempotency_key": "idem-test-001"
        }
        r1 = await client.post("/reservations", json=payload)
        r2 = await client.post("/reservations", json=payload)

    assert r1.status_code == 201
    assert r2.status_code == 201
    assert r1.json()["id"] == r2.json()["id"], "Idempotency key must return same reservation"


@pytest.mark.asyncio
async def test_availability_check():
    """Availability endpoint must reflect bookings correctly."""
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        # Book table 5
        await client.post("/reservations", json={
            "table_id": 5,
            "guest_name": "Eve",
            "date": TEST_DATE,
            "start_time": "14:00",
            "end_time": "16:00",
        })

        # Check same slot → not available
        r = await client.get("/tables/5/availability", params={
            "date": TEST_DATE,
            "start_time": "14:30",
            "end_time": "15:30",
        })
        assert r.status_code == 200
        assert r.json()["available"] is False

        # Check different slot → available
        r2 = await client.get("/tables/5/availability", params={
            "date": TEST_DATE,
            "start_time": "16:00",
            "end_time": "18:00",
        })
        assert r2.json()["available"] is True


@pytest.mark.asyncio
async def test_cancel_reservation():
    """Cancel a reservation — slot must become available again."""
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        r = await client.post("/reservations", json={
            "table_id": 1,
            "guest_name": "Frank",
            "date": "2026-11-01",
            "start_time": "09:00",
            "end_time": "10:00",
        })
        assert r.status_code == 201
        res_id = r.json()["id"]

        del_r = await client.delete(f"/reservations/{res_id}")
        assert del_r.status_code == 204

        # Slot should be available again
        avail = await client.get("/tables/1/availability", params={
            "date": "2026-11-01",
            "start_time": "09:00",
            "end_time": "10:00",
        })
        assert avail.json()["available"] is True
