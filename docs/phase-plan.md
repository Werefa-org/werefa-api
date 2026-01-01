# Werefa backend — phased implementation plan

This document is the **high-level execution plan** for building Werefa on top of this repository. It aligns with the product specification in [`doc/spec.md`](../doc/spec.md) while treating **this codebase** (FastAPI, SQLModel, PostgreSQL) as the source of truth for stack and structure. Where the spec mentions other stacks (e.g. Node.js), follow **requirements and data concepts**, not those implementation details.

---

## Table of contents

1. [Goals and principles](#1-goals-and-principles)
2. [Phase 0 — Foundation and adoption](#phase-0--foundation-and-adoption)
3. [Phase 1 — Domain model and REST API (MVP spine)](#phase-1--domain-model-and-rest-api-mvp-spine)
4. [Phase 2 — Hybrid FIFO engine and concurrency](#phase-2--hybrid-fifo-engine-and-concurrency)
5. [Phase 3 — Real-time updates](#phase-3--real-time-updates)
6. [Phase 4 — Discovery and geospatial search](#phase-4--discovery-and-geospatial-search)
7. [Phase 5 — Integrity, trust, and notifications](#phase-5--integrity-trust-and-notifications)
8. [Phase 6 — Hardening and scale](#phase-6--hardening-and-scale)
9. [Specification cross-reference](#specification-cross-reference)
10. [Quality and scalability guardrails](#quality-and-scalability-guardrails)

---

## 1. Goals and principles

- **Vertical slices**: Each phase should leave the system **runnable, testable, and demoable**.
- **PostgreSQL first**: ACID transactions for ticket creation and queue updates; schema in **3NF**; **snake_case** table names (see spec §4.7).
- **Clear boundaries**: Thin HTTP routers; business rules in **service** modules; persistence via CRUD/repositories—one consistent style per area.
- **Additive evolution**: Prefer new tables and migrations over breaking existing APIs without version bumps.

---

## Phase 0 — Foundation and adoption

**Status:** Completed for this repo (package rename, tooling, env patterns).

**Objectives**

- Stable Python package layout (`werefa`), dependency management (`uv`), CI, and local run paths (with or without Docker).
- Environment variables and secrets documented; database connectivity (including managed Postgres with TLS when required).
- Baseline auth (JWT, users) retained from the template as the **account layer** for all actors.

**Exit criteria**

- Application starts; migrations apply; tests can run against a real database; project naming reflects Werefa where appropriate.

---

## Phase 1 — Domain model and REST API (MVP spine)

**Goal:** Introduce core **Werefa entities** and a **REST API** so providers, customers, and admins can exercise the main flows without real-time or advanced geo yet.

### 1.1 Spec alignment (what Phase 1 must support)

| Spec area | Reference | Phase 1 scope |
|-----------|-----------|-----------------|
| Actors | §3.4.2.2 (Service seeker, Service provider, System administrator) | Model **roles** via `is_superuser` (admin) + **provider membership** (staff/owner) + authenticated **customer**. |
| Service-specific queues | FR-01, FR-10 | **Provider** + **ServiceItem** (name, duration, price); queues are scoped per **service line** (see decision below). |
| Multi-channel + unified FIFO | FR-02, FR-03 | **QueueEntry** with `source` (remote vs walk-in); single ordered wait list per service—full **conflict-free** merging hardened in Phase 2. |
| Provider controls | FR-09 (partial) | Ticket **status** and minimal transitions (e.g. list queue, mark states)—full “call next / recall / pause” polish in Phases 2–3. |
| Data dictionary | §3.5.1 Table 20 | Implement **Provider**, **ServiceItem**, **QueueEntry**; extend **User** minimally (e.g. optional `phone_number`) as needed. |

**Product decision (lock early):** **One FIFO queue per `ServiceItem`** (one line per offered service at a business). This matches “select Service Package then join” (UC-02) and keeps ordering rules simple.

### 1.2 Data model (high level)

| Concept | Purpose |
|---------|---------|
| **User** | Existing account table; extend with optional profile fields aligned to spec (e.g. phone) without blocking MVP. |
| **Provider** | Business/tenant: display name, slug/QR identifier, open/paused flags, verification status (stub), optional geofence radius, location fields (floats or PostGIS later). |
| **ProviderMembership** | Links `user_id` + `provider_id` + role (`owner` / `staff`). |
| **ServiceItem** | Services offered: `provider_id`, name, `avg_duration`, price, active flag. |
| **QueueEntry** | Ticket: `service_item_id`, optional `user_id`, guest name for walk-ins, display number, `status`, `source`, timestamps. |

**Rules to enforce in logic or DB**

- **UC-02 E2**: A user should not hold two **active** tickets (e.g. `waiting` / `serving`) simultaneously—unique partial index or transactional check.

### 1.3 API (REST, under `/api/v1`)

- **Admin** (`is_superuser`): provider lifecycle minimum (create/list; verification fields optional).
- **Provider staff** (membership): CRUD services; list/update tickets for their provider; pause/resume provider acceptance of joins (flags).
- **Customer**: join queue (auth); fetch own ticket(s); read public provider/service listings.
- **Public**: provider profile by slug (foundation for QR deep links).

### 1.4 Implementation order (recommended)

1. Enums (`TicketStatus`, `TicketSource`, `VerificationStatus`, membership roles).
2. SQLModel tables + relationships + Alembic migration(s).
3. CRUD or repository modules by domain (`providers`, `services`, `tickets`).
4. Service layer for enqueue / list / basic status changes (transactions from day one).
5. Routers + OpenAPI tags + dependency injection for authorization.
6. Tests: routes, concurrency on double-join, membership checks.

### 1.5 Explicitly out of Phase 1

- WebSockets / SSE, push/SMS, EWT algorithms (FR-06, FR-07, FR-08).
- Full geofence **enforcement** (FR-04, FR-05)—may store radius; enforcement in Phase 4.
- DemandLog, full reviews (FR-11), no-show **penalty automation** (FR-12)—stubs or later phases.
- PostGIS-heavy design—optional: plain lat/lng in Phase 1; migrate to PostGIS in Phase 4 if needed.

### 1.6 Exit criteria

- Migrations apply cleanly; seeded or manual provider + services + tickets flow works end-to-end via API.
- Role separation verified by tests; documented OpenAPI for mobile and web clients.

---

## Phase 2 — Hybrid FIFO engine and concurrency

**Goal:** One **deterministic**, **conflict-free** FIFO per service line for **remote** and **walk-in** sources (FR-03).

**Work**

- Transactional enqueue with explicit ordering (`joined_at` and/or monotonic sequence per service line).
- Row-level locking or equivalent so concurrent joins cannot duplicate positions or skip numbers.
- Walk-in vs app as `source` only—same queue table and code path.
- Load-oriented tests for concurrent joins.

**Exit criteria**

- Concurrency tests pass; documented semantics for ordering under failure/retry.

---

## Phase 3 — Real-time updates

**Status:** Core implementation completed (WebSocket streams, authz parity, Redis-ready fan-out, versioned events).

**Goal:** Propagate queue state within NFR latency targets (spec: sub-second to few-second sync—validate in staging).

**Work**

- Choose one: **WebSockets** (FastAPI-native) and/or **SSE** for server→client; add **Redis pub/sub** only if multiple worker processes must broadcast the same queue.
- Event payloads: queue id, ticket id, position, status—minimal and versioned.
- Authenticated subscriptions; mirror REST permissions.

**Exit criteria**

- Multiple clients observe consistent updates for the same queue under normal load.

---

## Phase 4 — Discovery and geospatial search

**Status:** In progress (initial provider discovery endpoint with distance-based ordering and filters).

**Goal:** “Near me” and provider discovery (FR-01 discovery aspects, UC-01).

**Work**

- Indexes on location; **PostGIS** (`GEOGRAPHY`) if the spec’s spatial rules are required at scale (§4.7.2–4.7.3).
- Public vs private providers; filters (category, wait hints when data exists).
- Optional “load factor” derived from queue depth / estimates when Phase 2–3 metrics exist.

**Exit criteria**

- Bounded-radius queries perform acceptably on realistic datasets.

---

## Phase 5 — Integrity, trust, and notifications

**Goal:** No-show handling, reviews gated on completion, optional monetization fields (spec Table 20).

**Work**

- No-show counters, temporary blocks (FR-12); configurable thresholds.
- Reviews only after provider-completed ticket (FR-11).
- Notification channels: start with email; abstract SMS/push behind interfaces.
- Liveness / geofence **enforcement** workflows (FR-05) as policy on top of Phase 4 location model.

**Exit criteria**

- Documented policies; audit-friendly state transitions for tickets and user reputation.

---

## Phase 6 — Hardening and scale

**Goal:** Production readiness and stated capacity targets (e.g. concurrent joins per region—validate, don’t guess).

**Work**

- Rate limits, abuse protection on join endpoints.
- Observability: structured logs, Sentry tags (`provider_id`, `queue_id`, `ticket_id`).
- Load tests on hot paths; connection pool tuning; optional read replicas later.
- Deployment alignment (Traefik, TLS, secrets) per existing `deployment.md` patterns.

**Exit criteria**

- SLOs documented; failure modes tested (DB restart, worker crash, websocket reconnect).

---

## Specification cross-reference

| Spec section | Content |
|--------------|---------|
| §3.2 | Functional requirements FR-01–FR-12 |
| §3.3 | Non-functional requirements (latency, scale, usability) |
| §3.4.2.2 | Actors: seeker, provider, administrator |
| §3.4.2.3 / Tables 6–19 | Use cases (UC-01–UC-14) driving API and state machines |
| §3.5.1 Table 20 | Data dictionary: User, Provider, ServiceItem, QueueEntry, etc. |
| §4.7 | PostgreSQL, ORM mapping rules, normalization, spatial notes |

---

## Quality and scalability guardrails

- **Transactions** for any operation that changes ticket order or shared counters.
- **API versioning**: keep `/api/v1` stable; introduce `/api/v2` only for breaking changes.
- **Secrets**: never commit; rotate if leaked; use environment-based config (see `werefa.core.config`).
- **Tests**: maintain high coverage on queue and auth paths; add concurrency tests when touching Phase 2+.
- **Single responsibility**: new features add columns or tables rather than overloading `User` or `Provider` with unrelated flags without migration discipline.

---

## Document history

| Version | Notes |
|---------|--------|
| 1.0 | Initial phased plan derived from `doc/spec.md` and agreed backend direction (FastAPI/SQLModel). |
