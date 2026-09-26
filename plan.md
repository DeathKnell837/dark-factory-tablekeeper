# Dark Factory — tablekeeper Stage 1

## Goal
Build a restaurant reservation service where a table can never be double-booked, under any conditions including concurrent requests, retries, and repeated submissions.

## Seats in this factory
- **Planner Agent** — decomposes work, defines done criteria, tracks progress
- **Executor Agent** — implements code to meet done criteria
- **Reviewer Agent** — verifies done criteria are met with tests, reports PASS or FAIL

## Stage 1 Work Units

### WU-1: Core reservation API
**Done criteria:**
1. `POST /reservations` creates a reservation and returns 201 with the reservation object
2. `GET /reservations/{id}` returns the reservation or 404
3. `DELETE /reservations/{id}` cancels a reservation and returns 204
4. `GET /tables/{id}/availability?date=&start_time=&end_time=` returns whether the slot is free
5. `GET /tables` lists all tables

**Constraints:**
- A reservation has: table_id, guest_name, guest_email (optional), date, start_time, end_time, timezone (default UTC)
- start_time must be before end_time — return 400 otherwise

### WU-2: No double-booking — sequential
**Done criteria:**
1. Two sequential POST requests for the same table, date, and overlapping time window — the second returns 409 Conflict
2. Bookings that do NOT overlap on time do not conflict

### WU-3: No double-booking — concurrent (the hard constraint)
**Done criteria:**
1. 50 concurrent POST requests for the same table/date/time slot — exactly 1 returns 201, the other 49 return 409
2. This must hold reliably across multiple runs

**Implementation note for Executor:** Use `SELECT ... FOR UPDATE` in PostgreSQL inside a transaction to lock the row check. This prevents concurrent transactions from both seeing "no conflict" simultaneously.

### WU-4: Idempotency
**Done criteria:**
1. If a POST includes an `idempotency_key` field and that key was already used, return the original reservation (201) without creating a duplicate
2. Two requests with the same idempotency_key must return the same reservation ID

## Stack
- Python 3.12 + FastAPI + asyncpg + SQLAlchemy 2.0 async
- PostgreSQL 16 (via Docker)
- Docker + docker-compose with `internal: true` network (no outbound internet)

## Files already created (Executor: use these as your base)
- `stage-1/app/main.py` — FastAPI app with lifespan db init
- `stage-1/app/db.py` — SQLAlchemy models, async engine, seeded tables
- `stage-1/app/schemas.py` — Pydantic request/response models
- `stage-1/app/routes.py` — API routes with FOR UPDATE locking
- `stage-1/requirements.txt` — pinned dependencies
- `stage-1/Dockerfile` — builds clean image
- `stage-1/docker-compose.yml` — internal network, postgres healthcheck
- `stage-1/tests/test_reservations.py` — full test suite including concurrent test

## Reviewer: run these tests
```bash
cd stage-1
docker-compose up -d
sleep 10
pip install httpx pytest pytest-asyncio
pytest tests/ -v
docker-compose down -v
```
All 6 tests must pass. The critical one is `test_no_double_booking_concurrent`.

## Done state for Stage 1
- All 6 tests pass
- `docker-compose up` starts cleanly from scratch with no errors
- Service responds at `http://localhost:8000/health`
- No outbound network calls made at runtime
