import pytest
import asyncio
import httpx

BASE_URL = "http://localhost:8000"


@pytest.fixture(autouse=True)
def clean_database():
    """Ensure every test runs against a clean, isolated database state."""
    httpx.post(f"{BASE_URL}/testing/reset")


@pytest.mark.asyncio
async def test_health():
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        resp = await client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["stage"] == 3
        assert data["waitlist_supported"] is True


@pytest.mark.asyncio
async def test_capacity_validation():
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        # Table 1 has capacity 2. Party of 4 must be rejected with 400
        payload_invalid = {
            "table_id": 1,
            "guest_name": "Over Capacity Party",
            "party_size": 4,
            "date": "2026-11-01",
            "start_time": "18:00:00",
            "end_time": "20:00:00",
            "timezone": "America/New_York",
        }
        resp = await client.post("/reservations", json=payload_invalid)
        assert resp.status_code == 400
        assert "exceeds table capacity" in resp.json()["detail"].lower()

        # Valid party of 2 succeeds
        payload_valid = {
            "table_id": 1,
            "guest_name": "Fitting Party",
            "party_size": 2,
            "date": "2026-11-01",
            "start_time": "18:00:00",
            "end_time": "20:00:00",
            "timezone": "America/New_York",
        }
        resp_valid = await client.post("/reservations", json=payload_valid)
        assert resp_valid.status_code == 201
        res_data = resp_valid.json()
        assert res_data["table_id"] == 1
        assert res_data["party_size"] == 2


@pytest.mark.asyncio
async def test_best_fit_table_assignment():
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        # Request for party of 4 without specifying table_id
        payload = {
            "guest_name": "Auto Assign Party of 4",
            "party_size": 4,
            "date": "2026-11-02",
            "start_time": "19:00:00",
            "end_time": "21:00:00",
            "timezone": "America/New_York",
        }
        resp = await client.post("/reservations", json=payload)
        assert resp.status_code == 201
        data = resp.json()
        # Should pick Table 3 or Table 4 (which are 4-tops), not 2-top or 8-top
        assert data["table_id"] in [3, 4]
        assert data["party_size"] == 4


@pytest.mark.asyncio
async def test_waitlist_fifo_queue():
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        # Table 2 is a 2-top. Book it first
        book_resp = await client.post("/reservations", json={
            "table_id": 2,
            "guest_name": "Initial Booker",
            "party_size": 2,
            "date": "2026-11-03",
            "start_time": "18:00:00",
            "end_time": "20:00:00",
            "timezone": "America/New_York",
        })
        assert book_resp.status_code == 201

        # Second booking fails with 409
        conflict_resp = await client.post("/reservations", json={
            "table_id": 2,
            "guest_name": "Conflicting Booker",
            "party_size": 2,
            "date": "2026-11-03",
            "start_time": "18:30:00",
            "end_time": "19:30:00",
            "timezone": "America/New_York",
        })
        assert conflict_resp.status_code == 409

        # Guest A joins waitlist
        wl_a = await client.post("/waitlist", json={
            "guest_name": "Waitlist Guest A",
            "party_size": 2,
            "date": "2026-11-03",
            "start_time": "18:00:00",
            "end_time": "20:00:00",
            "timezone": "America/New_York",
        })
        assert wl_a.status_code == 201
        data_a = wl_a.json()
        assert data_a["status"] == "waiting"
        pos_a = data_a["queue_position"]

        # Guest B joins waitlist shortly after
        wl_b = await client.post("/waitlist", json={
            "guest_name": "Waitlist Guest B",
            "party_size": 2,
            "date": "2026-11-03",
            "start_time": "18:00:00",
            "end_time": "20:00:00",
            "timezone": "America/New_York",
        })
        assert wl_b.status_code == 201
        data_b = wl_b.json()
        assert data_b["status"] == "waiting"
        assert data_b["queue_position"] > pos_a


@pytest.mark.asyncio
async def test_atomic_auto_promotion_on_cancellation():
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        # Table 5 is a 6-top. Book it
        book_resp = await client.post("/reservations", json={
            "table_id": 5,
            "guest_name": "Original Host",
            "party_size": 6,
            "date": "2026-11-04",
            "start_time": "19:00:00",
            "end_time": "21:00:00",
            "timezone": "America/New_York",
        })
        assert book_resp.status_code == 201
        res_id = book_resp.json()["id"]

        # Add waitlist guest Alice for same slot
        wl_resp = await client.post("/waitlist", json={
            "guest_name": "Alice in Waitlist",
            "party_size": 5,
            "date": "2026-11-04",
            "start_time": "19:00:00",
            "end_time": "21:00:00",
            "timezone": "America/New_York",
        })
        assert wl_resp.status_code == 201
        wl_id = wl_resp.json()["id"]

        # Cancel the original reservation
        cancel_resp = await client.delete(f"/reservations/{res_id}")
        assert cancel_resp.status_code == 200
        cancel_data = cancel_resp.json()
        assert cancel_data["cancelled_reservation_id"] == res_id
        assert cancel_data["promoted_waitlist_entry_id"] == wl_id
        assert cancel_data["promoted_reservation"] is not None
        assert cancel_data["promoted_reservation"]["guest_name"] == "Alice in Waitlist"
        assert cancel_data["promoted_reservation"]["table_id"] == 5

        # Verify waitlist record is marked 'promoted'
        wl_check = await client.get(f"/waitlist/{wl_id}")
        assert wl_check.status_code == 200
        assert wl_check.json()["status"] == "promoted"
        assert wl_check.json()["promoted_reservation_id"] == cancel_data["promoted_reservation"]["id"]


@pytest.mark.asyncio
async def test_concurrent_50_capacity_locking():
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=60.0) as client:
        # Table 6 is an 8-top. 50 concurrent bookings for party of 8
        async def send_booking(idx: int):
            return await client.post("/reservations", json={
                "table_id": 6,
                "guest_name": f"Concurrent Guest #{idx}",
                "party_size": 8,
                "date": "2026-11-05",
                "start_time": "20:00:00",
                "end_time": "22:00:00",
                "timezone": "America/New_York",
            })

        tasks = [send_booking(i) for i in range(50)]
        results = await asyncio.gather(*tasks)

        status_codes = [r.status_code for r in results]
        success_count = status_codes.count(201)
        conflict_count = status_codes.count(409)

        # STRICT CONSTRAINTS: Exactly 1 must succeed, exactly 49 must be rejected
        assert success_count == 1, f"Expected exactly 1 success, got {success_count}"
        assert conflict_count == 49, f"Expected 49 conflicts, got {conflict_count}"


@pytest.mark.asyncio
async def test_waitlist_cancellation():
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        # Add guest to waitlist
        wl_resp = await client.post("/waitlist", json={
            "guest_name": "Cancelled Waitlist Guest",
            "party_size": 2,
            "date": "2026-11-06",
            "start_time": "18:00:00",
            "end_time": "20:00:00",
            "timezone": "America/New_York",
        })
        assert wl_resp.status_code == 201
        wl_id = wl_resp.json()["id"]

        # Cancel waitlist entry
        del_resp = await client.delete(f"/waitlist/{wl_id}")
        assert del_resp.status_code == 204

        # Verify status is now 'cancelled'
        get_resp = await client.get(f"/waitlist/{wl_id}")
        assert get_resp.status_code == 200
        assert get_resp.json()["status"] == "cancelled"
