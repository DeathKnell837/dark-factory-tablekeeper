import pytest
import asyncio
import httpx

BASE_URL = "http://localhost:8000"


@pytest.fixture(autouse=True)
def clean_database():
    """Ensure every test runs against a clean, isolated database state."""
    httpx.post(f"{BASE_URL}/testing/reset")


@pytest.mark.asyncio
async def test_health_and_probes():
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        # Standard health
        h = await client.get("/health")
        assert h.status_code == 200
        assert h.json()["stage"] == 4

        # Kubernetes liveness probe
        live = await client.get("/health/live")
        assert live.status_code == 200
        assert live.json()["status"] == "alive"

        # Kubernetes readiness probe
        ready = await client.get("/health/ready")
        assert ready.status_code == 200
        assert ready.json()["status"] == "ready"


@pytest.mark.asyncio
async def test_metrics_endpoint():
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        metrics = await client.get("/metrics")
        assert metrics.status_code == 200
        data = metrics.json()
        assert data["factory_status"] == "NOMINAL"
        assert data["double_booking_violations"] == 0
        assert "collisions_prevented" in data


@pytest.mark.asyncio
async def test_audit_trail_creation_and_cancellation():
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        # 1. Create reservation
        create_resp = await client.post("/reservations", json={
            "table_id": 1,
            "guest_name": "Audited Guest",
            "party_size": 2,
            "date": "2026-12-01",
            "start_time": "18:00:00",
            "end_time": "20:00:00",
            "timezone": "America/New_York",
        })
        assert create_resp.status_code == 201
        res_id = create_resp.json()["id"]

        # Verify audit log for creation
        logs_resp = await client.get("/audit-logs?event_type=RESERVATION_CREATED")
        assert logs_resp.status_code == 200
        logs = logs_resp.json()
        assert len(logs) >= 1
        assert logs[0]["reservation_id"] == res_id
        assert logs[0]["guest_name"] == "Audited Guest"

        # 2. Cancel reservation
        del_resp = await client.delete(f"/reservations/{res_id}")
        assert del_resp.status_code == 200

        # Verify audit log for cancellation
        logs_del = await client.get("/audit-logs?event_type=RESERVATION_CANCELLED")
        assert logs_del.status_code == 200
        assert len(logs_del.json()) >= 1
        assert logs_del.json()[0]["reservation_id"] == res_id


@pytest.mark.asyncio
async def test_audit_idempotent_replay():
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        payload = {
            "table_id": 2,
            "guest_name": "Idempotent Guest",
            "party_size": 2,
            "date": "2026-12-02",
            "start_time": "19:00:00",
            "end_time": "21:00:00",
            "timezone": "America/New_York",
            "idempotency_key": "audit-idemp-key-12345",
        }
        # First call creates
        r1 = await client.post("/reservations", json=payload)
        assert r1.status_code == 201

        # Second call returns existing
        r2 = await client.post("/reservations", json=payload)
        assert r2.status_code == 200 or r2.status_code == 201
        assert r2.json()["id"] == r1.json()["id"]

        # Verify audit log recorded IDEMPOTENT_REPLAY
        logs = await client.get("/audit-logs?event_type=IDEMPOTENT_REPLAY")
        assert logs.status_code == 200
        assert len(logs.json()) >= 1


@pytest.mark.asyncio
async def test_audit_collision_blocked():
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        # Book table
        r1 = await client.post("/reservations", json={
            "table_id": 3,
            "guest_name": "Holder",
            "party_size": 4,
            "date": "2026-12-03",
            "start_time": "18:00:00",
            "end_time": "20:00:00",
            "timezone": "America/New_York",
        })
        assert r1.status_code == 201

        # Conflicting booking
        r2 = await client.post("/reservations", json={
            "table_id": 3,
            "guest_name": "Conflicter",
            "party_size": 4,
            "date": "2026-12-03",
            "start_time": "18:30:00",
            "end_time": "19:30:00",
            "timezone": "America/New_York",
        })
        assert r2.status_code == 409

        # Verify audit log recorded COLLISION_BLOCKED
        logs = await client.get("/audit-logs?event_type=COLLISION_BLOCKED")
        assert logs.status_code == 200
        assert len(logs.json()) >= 1


@pytest.mark.asyncio
async def test_stage4_concurrent_50_zero_double_booking():
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=60.0) as client:
        async def send_booking(idx: int):
            return await client.post("/reservations", json={
                "table_id": 6,
                "guest_name": f"Stage 4 Load Guest #{idx}",
                "party_size": 8,
                "date": "2026-12-04",
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
        assert success_count == 1, f"Expected 1 success, got {success_count}"
        assert conflict_count == 49, f"Expected 49 conflicts, got {conflict_count}"

        # Verify metrics confirm zero double bookings
        metrics_resp = await client.get("/metrics")
        assert metrics_resp.status_code == 200
        m = metrics_resp.json()
        assert m["double_booking_violations"] == 0
        assert m["collisions_prevented"] >= 49


@pytest.mark.asyncio
async def test_full_lifecycle_waitlist_auto_promotion():
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        # 1. Book Table 4 (4-top)
        r1 = await client.post("/reservations", json={
            "table_id": 4,
            "guest_name": "First Guest",
            "party_size": 4,
            "date": "2026-12-05",
            "start_time": "19:00:00",
            "end_time": "21:00:00",
            "timezone": "America/New_York",
        })
        assert r1.status_code == 201
        res1_id = r1.json()["id"]

        # 2. Waitlist Guest
        wl = await client.post("/waitlist", json={
            "guest_name": "Waitlisted Hopeful",
            "party_size": 3,
            "date": "2026-12-05",
            "start_time": "19:00:00",
            "end_time": "21:00:00",
            "timezone": "America/New_York",
        })
        assert wl.status_code == 201
        wl_id = wl.json()["id"]

        # 3. Cancel First Guest -> Auto promotes Waitlisted Hopeful
        cancel = await client.delete(f"/reservations/{res1_id}")
        assert cancel.status_code == 200
        c_data = cancel.json()
        assert c_data["promoted_waitlist_entry_id"] == wl_id
        assert c_data["promoted_reservation"]["guest_name"] == "Waitlisted Hopeful"

        # 4. Verify audit trail logged WAITLIST_PROMOTED
        audit_promo = await client.get("/audit-logs?event_type=WAITLIST_PROMOTED")
        assert audit_promo.status_code == 200
        assert len(audit_promo.json()) >= 1
