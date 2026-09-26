# Dark Factory: tablekeeper

**WeAreDevelopers x BAND Hackathon (Dark Factory Edition) | Track: `tablekeeper`**

> An autonomous AI software factory operating inside **BAND Desktop** that planned, developed, tested, and production-hardened a mission-critical restaurant reservation system where a table can **never** be double-booked under any condition — including high concurrency, network retries, and cross-timezone collisions.

---

## 🏭 Factory Architecture & Seats

Our factory lives in **BAND Desktop** (Room `7a423cfb-9444-4888-8732-a0e1dee3f0bb`) with 3 distinct agent seats connected via the `band-sdk` WebSocket layer:

| Seat | Handle | Role & Mandate |
| :--- | :--- | :--- |
| **Planner Agent** | `@rogiebacanto2002/planner-agent` | Decomposes track briefs into structured work units with unambiguous done criteria. Coordinates execution milestones. |
| **Executor Agent** | `@rogiebacanto2002/executor-agent` | Implements FastAPI endpoints, PostgreSQL models, row-level concurrency locking, and business logic. |
| **Reviewer Agent** | `@rogiebacanto2002/reviewer-agent` | Develops and executes automated test suites, concurrency stress benchmarks, and signs off with `PASS` or `FAIL`. |

All seat mandates in [`mandates/`](file:///mandates/) are **100% generic** and domain-agnostic (meeting the hackathon requirement of never naming track-specific details). Full interaction history is exported in [`band-room-export.md`](file:///band-room-export.md).

---

## 📦 Progressive Stages Overview

| Stage | Focus Area | Key Innovations & Hard Constraints | Test Result |
| :--- | :--- | :--- | :--- |
| [`stage-1/`](file:///stage-1/) | **Core Concurrency Locking** | Pessimistic locking (`SELECT FOR UPDATE`) on Table resource; atomic overlap prevention; 50 concurrent requests guarantee exactly 1 booking. | **7 / 7 PASSED (100%)** |
| [`stage-2/`](file:///stage-2/) | **Timezones & Idempotency** | Normalized UTC `TIMESTAMPTZ` storage; cross-timezone collision detection (e.g., NY 19:00 EDT vs Tokyo 08:30 JST); SHA-256 payload-hashed idempotency replay safety; 50 concurrent requests across 5 global timezones. | **7 / 7 PASSED (100%)** |
| [`stage-3/`](file:///stage-3/) | **Capacity & Atomic Waitlist** | Seating capacity enforcement (2-top, 4-top, 6-top, 8-top); best-fit table allocation; FIFO waitlist (`/waitlist`); atomic auto-promotion of waitlisted parties upon cancellation (`DELETE /reservations/{id}`) without race conditions. | **7 / 7 PASSED (100%)** |
| [`stage-4/`](file:///stage-4/) | **Production Hardening & Observability** | Immutable operational audit ledger (`audit_logs`); real-time observability `/metrics` (tracking conflicts prevented, double_bookings=0); `/health/live` & `/health/ready` probes; deadlock resilience and pool tuning. | **7 / 7 PASSED (100%)** |

---

## 🔒 Network Isolation Guarantee

In compliance with the hackathon rules, all stage containers are run with **complete outbound network isolation** using Docker internal bridge networks:

```yaml
networks:
  internal:
    driver: bridge
    internal: true
```

The services start, initialize their databases, and execute their full test suites **with zero external internet calls at runtime**.

---

## 🚀 How to Run and Test Each Stage

### Stage 1: Core Concurrency Locking
```bash
cd stage-1
docker compose up -d --build
# Execute tests inside clean isolated container:
docker compose exec app pytest /app/tests -v
docker compose down -v
```

### Stage 2: Timezone Normalization & Safe Idempotency
```bash
cd stage-2
docker compose up -d --build
# Execute tests inside clean isolated container:
docker compose exec app pytest /app/tests -v
docker compose down -v
```

### Stage 3: Table Capacity & Waitlist Auto-Promotion
```bash
cd stage-3
docker compose up -d --build
# Execute tests inside clean isolated container:
docker compose exec app pytest /app/tests -v
docker compose down -v
```

### Stage 4: Production Hardening, Audit Logs & Metrics
```bash
cd stage-4
docker compose up -d --build
# Execute tests inside clean isolated container:
docker compose exec app pytest /app/tests -v
docker compose down -v
```

---

## 📊 Live Metrics & Audit Verification (Stage 4)

In Stage 4, query the real-time observability and audit endpoints:

- **Metrics**: `GET http://localhost:8003/metrics`
  ```json
  {
    "total_reservations_created": 3,
    "active_reservations": 2,
    "cancellations_count": 1,
    "waitlist_active_count": 0,
    "waitlist_promoted_count": 1,
    "collisions_prevented": 49,
    "idempotent_replays": 1,
    "double_booking_violations": 0,
    "factory_status": "NOMINAL"
  }
  ```
- **Audit Trail**: `GET http://localhost:8003/audit-logs?event_type=WAITLIST_PROMOTED`
- **Liveness Probe**: `GET http://localhost:8003/health/live`
- **Readiness Probe**: `GET http://localhost:8003/health/ready`

---

## 🎥 Submission Checklist

- [x] **Band of Coding Agents**: 3 distinct seats (Planner, Executor, Reviewer) active in BAND Desktop room `7a423cfb-9444-4888-8732-a0e1dee3f0bb`.
- [x] **Generic Seat Mandates**: `mandates/planner.md`, `mandates/executor.md`, `mandates/reviewer.md` (no domain-specific keywords).
- [x] **Factory Description**: `factory-description.md` detailing the handoff protocol.
- [x] **Room Export**: `band-room-export.md` capturing all multi-agent discussions, work breakdowns, and sign-offs.
- [x] **All 4 Stages Complete**: `stage-1/`, `stage-2/`, `stage-3/`, `stage-4/` each self-contained, buildable, and passing 100% of tests.
- [x] **Internal Isolated Network**: `internal: true` on all Docker networks.
- [ ] **Video Presentation**: Screen recording of BAND Desktop room showing agents in action + walkthrough.
