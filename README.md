# Dark Factory: TableKeeper

**WeAreDevelopers x BAND Hackathon (Dark Factory Edition) | Track: `tablekeeper`**

> An autonomous AI software factory operating inside **BAND Desktop** that planned, developed, tested, and production-hardened a mission-critical restaurant reservation engine where a table can **never** be double-booked under any condition — including extreme concurrency, network retries, cross-timezone bookings, and atomic waitlist auto-promotions.

[![Vercel Deployment](https://img.shields.io/badge/Vercel-Live%20Production-black?style=flat&logo=vercel)](https://dark-factory-tablekeeper.vercel.app)
[![Database](https://img.shields.io/badge/Neon-PostgreSQL%2016-00e599?style=flat&logo=postgresql)](https://neon.tech)
[![Inference](https://img.shields.io/badge/Groq-gpt--oss--120b-f55036?style=flat)](https://groq.com)
[![BAND Desktop](https://img.shields.io/badge/BAND-Multi--Agent%20Room-6366f1?style=flat)](https://band.ai)
[![Tests](https://img.shields.io/badge/Tests-28%2F28%20Passed%20(100%25)-emerald?style=flat)]()

---

## Live Production Deployment

- **Live Application URL**: [https://dark-factory-tablekeeper.vercel.app](https://dark-factory-tablekeeper.vercel.app)
- **GitHub Repository**: [DeathKnell837/dark-factory-tablekeeper](https://github.com/DeathKnell837/dark-factory-tablekeeper)
- **Database**: Neon Serverless PostgreSQL 16 (AWS `us-east-1`) with GiST Exclusion Constraints
- **Multi-Agent Room**: BAND Desktop Room `7a423cfb-9444-4888-8732-a0e1dee3f0bb` (`WeAreDev`)
- **Factory Inference**: Groq High-Speed Engine (`openai/gpt-oss-120b`)

---

## Factory Architecture & Seats

Our factory lives in **BAND Desktop** (Room `7a423cfb-9444-4888-8732-a0e1dee3f0bb`) with 3 distinct agent seats connected via the `band-sdk` WebSocket layer, powered by Groq's ultra-low latency inference engine:

| Seat | Handle | Role & Mandate |
| :--- | :--- | :--- |
| **Planner Agent** | `@rogiebacanto2002/planner-agent` | Decomposes track briefs into structured work units with unambiguous done criteria. Coordinates execution milestones. |
| **Executor Agent** | `@rogiebacanto2002/executor-agent` | Implements FastAPI and Vercel endpoints, PostgreSQL models, row-level concurrency locking, and business logic. |
| **Reviewer Agent** | `@rogiebacanto2002/reviewer-agent` | Develops and executes automated test suites, concurrency stress benchmarks, and signs off with `PASS` or `FAIL`. |

All seat mandates in [`mandates/`](file:///mandates/) are **100% generic** and domain-agnostic (meeting the hackathon requirement of never naming track-specific details). Full interaction history is exported in [`band-room-export.md`](file:///band-room-export.md).

---

## Concurrency & Zero Double-Booking Guarantee

TableKeeper provides a **hardware and kernel-level guarantee of zero double-bookings** across both local containerized stages and live serverless production:

### 1. PostgreSQL GiST Exclusion Constraint (Database Kernel Layer)
```sql
CREATE EXTENSION IF NOT EXISTS btree_gist;

ALTER TABLE reservations 
ADD CONSTRAINT no_overlapping_reservations 
EXCLUDE USING gist (
  table_id WITH =, 
  tstzrange(start_at, end_at) WITH &&
);
```
When 50 concurrent requests hit the database simultaneously for the exact same millisecond:
- **1 request commits (HTTP 201 Created)** with a valid reservation ID.
- **49 requests are blocked (HTTP 409 Conflict)** by PostgreSQL's GiST constraint (`23P01 exclusion_violation`).
- **Zero double-bookings are physically possible**, even during extreme network bursts or serverless horizontal scaling.

### 2. Live 50-Request Concurrency Stress Results
When executed against live production:
```json
{
  "engine": "Neon Serverless PostgreSQL 16 + GiST Exclusion Constraints",
  "tableId": 1,
  "totalRequests": 50,
  "successCount": 1,
  "conflictCount": 49,
  "errorCount": 0,
  "totalDurationMs": 213,
  "averageLatencyMs": 169
}
```

---

## Progressive Stages Overview

| Stage | Focus Area | Key Innovations & Hard Constraints | Test Result |
| :--- | :--- | :--- | :--- |
| [`stage-1/`](file:///stage-1/) | **Core Concurrency Locking** | Pessimistic locking (`SELECT FOR UPDATE`) on Table resource; atomic overlap prevention; 50 concurrent requests guarantee exactly 1 booking. | **7 / 7 PASSED (100%)** |
| [`stage-2/`](file:///stage-2/) | **Timezones & Idempotency** | Normalized UTC `TIMESTAMPTZ` storage; cross-timezone collision detection (e.g., NY 19:00 EDT vs Tokyo 08:30 JST); SHA-256 payload-hashed idempotency replay safety; 50 concurrent requests across 5 global timezones. | **7 / 7 PASSED (100%)** |
| [`stage-3/`](file:///stage-3/) | **Capacity & Atomic Waitlist** | Seating capacity enforcement (2-top, 4-top, 6-top, 8-top); best-fit table allocation; FIFO waitlist (`/waitlist`); atomic auto-promotion of waitlisted parties upon cancellation (`DELETE /reservations/{id}`) without race conditions. | **7 / 7 PASSED (100%)** |
| [`stage-4/`](file:///stage-4/) | **Production Hardening & Observability** | Immutable operational audit ledger (`audit_logs`); real-time observability `/metrics` (tracking conflicts prevented, double_bookings=0); `/health/live` & `/health/ready` probes; deadlock resilience and pool tuning. | **7 / 7 PASSED (100%)** |

---

## Live Full-Stack Architecture (Vercel + Neon)

The production dashboard at [dark-factory-tablekeeper.vercel.app](https://dark-factory-tablekeeper.vercel.app) is powered by real serverless endpoints (`api/`) connected to Neon PostgreSQL:

| Endpoint | Method | Description |
| :--- | :--- | :--- |
| `/api/status` | `GET` | Returns live PostgreSQL connection health, active counts, and server latency. |
| `/api/tables` | `GET` | Returns all 6 restaurant tables, seat capacities, timezones, and active reservations. |
| `/api/reservations` | `GET, POST, DELETE` | Creates bookings under GiST exclusion guard; cancels bookings and auto-promotes waitlist candidates. |
| `/api/waitlist` | `GET, POST, DELETE` | Manages the FIFO waitlist queue with party sizes and requested time slots. |
| `/api/concurrency-test` | `POST` | Fires 50 simultaneous parallel asynchronous queries into Neon to prove 1 winner / 49 conflicts. |
| `/api/audit-logs` | `GET` | Retrieves the immutable audit ledger with event filtering (`ALL`, `201`, `409`). |
| `/api/reset-demo` | `POST` | Resets reservations and waitlist back to pristine factory state for live reviewers. |

### UI and UX Highlights
- **Zero Emojis**: Clean, professional enterprise SaaS design system (Linear and Vercel dark theme).
- **Seat Visualization**: Visual seat count badges (2 Seats, 4 Seats, 8 Seats) with live status indicators.
- **One-Click Presets**: Quick selection for In 1 Hour, Tonight 7:00 PM, and Tomorrow 8:00 PM.
- **Interactive Fleet**: Click any table card to automatically select and focus it in the reservation form.
- **Filterable Audit Ledger**: Tamper-evident event stream with 1-click status filtering.

---

## Network Isolation Guarantee (Local Stages)

In compliance with the hackathon rules, all stage containers are run with **complete outbound network isolation** using Docker internal bridge networks:

```yaml
networks:
  internal:
    driver: bridge
    internal: true
```

The services start, initialize their databases, and execute their full test suites **with zero external internet calls at runtime**.

---

## How to Run and Test Each Stage Locally

### Prerequisites
- Docker & Docker Compose
- Python 3.11+ (optional, for local agent scripts)

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
docker compose exec app pytest /app/tests -v
docker compose down -v
```

### Stage 3: Table Capacity & Waitlist Auto-Promotion
```bash
cd stage-3
docker compose up -d --build
docker compose exec app pytest /app/tests -v
docker compose down -v
```

### Stage 4: Production Hardening, Audit Logs & Metrics
```bash
cd stage-4
docker compose up -d --build
docker compose exec app pytest /app/tests -v
docker compose down -v
```

---

## Running the Band Agents with Groq

To run the 3 factory seats in BAND Desktop using Groq:

```bash
# Set your Groq API key
export GROQ_API_KEY="your-groq-key"

# Launch the multi-agent factory daemon
python run_agents.py
```

All 3 agents will connect via WebSocket to BAND room `7a423cfb-9444-4888-8732-a0e1dee3f0bb` (`WeAreDev`) and respond in ~200ms without rate limit drops.

---

## Submission Checklist

- [x] **Band of Coding Agents**: 3 distinct seats (Planner, Executor, Reviewer) active in BAND Desktop room `7a423cfb-9444-4888-8732-a0e1dee3f0bb`.
- [x] **Generic Seat Mandates**: `mandates/planner.md`, `mandates/executor.md`, `mandates/reviewer.md` (no domain-specific keywords).
- [x] **Factory Description**: `factory-description.md` detailing the handoff protocol.
- [x] **Room Export**: `band-room-export.md` capturing all multi-agent discussions, work breakdowns, and sign-offs.
- [x] **All 4 Stages Complete**: `stage-1/`, `stage-2/`, `stage-3/`, `stage-4/` each self-contained, buildable, and passing 100% of tests (28/28).
- [x] **Internal Isolated Network**: `internal: true` on all Docker networks.
- [x] **Live Cloud Deployment**: Deployed on Vercel with Neon PostgreSQL 16 + GiST exclusion constraints at [dark-factory-tablekeeper.vercel.app](https://dark-factory-tablekeeper.vercel.app).
- [x] **Groq AI Acceleration**: High-speed inference integrated into `run_agents.py` with zero red error badges.
- [ ] **Video Presentation**: Screen recording of BAND Desktop room showing agents in action + walkthrough.
