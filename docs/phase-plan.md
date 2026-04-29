# Werefa backend — comprehensive implementation plan

This document is the **single source of truth** for the next backend phases. It aligns with the product specification in [`doc.md`](./doc.md) (Chapter 3 functional requirements, scenarios A–F, and use cases UC-00 through UC-16) while treating this repository (FastAPI + SQLModel + PostgreSQL) as the authoritative stack. Where `doc.md` mentions other stacks (Node.js, Socket.io) or stack‑specific UX (phone OTP), this plan **adapts** to the current stack without dropping product intent.

> **Out of scope by explicit decision:** **FR-04 — Join-time provider geofencing** (no GPS check on join). Discovery filters by radius and provider radius config can stay; the **join API will not enforce** caller GPS vs `join_radius_m`. Every other FR/UC in `doc.md` is in scope.

---

## Table of contents

1. [Goals and principles](#1-goals-and-principles)
2. [Current state inventory](#2-current-state-inventory)
   - 2.1 Implemented today
   - 2.2 Partial / drifting from `doc.md`
   - 2.3 Missing entirely
   - 2.4 Defects to fix in flight
3. [Cross-cutting foundations (Phase F)](#3-cross-cutting-foundations-phase-f)
4. [Roadmap overview](#4-roadmap-overview)
5. [Phase 6 — Reviews and verified ratings (FR-11, UC-08)](#phase-6--reviews-and-verified-ratings-fr-11-uc-08)
6. [Phase 7 — No-show strikes and remote-join block (FR-12)](#phase-7--no-show-strikes-and-remote-join-block-fr-12)
7. [Phase 8 — Service-weighted moving-average EWT (FR-06, FR-01)](#phase-8--service-weighted-moving-average-ewt-fr-06-fr-01)
8. [Phase 9 — Provider broadcast messages (FR-08, UC-11)](#phase-9--provider-broadcast-messages-fr-08-uc-11)
9. [Phase 10 — Notifications channel & smart pre-alerts (FR-07)](#phase-10--notifications-channel--smart-pre-alerts-fr-07)
10. [Phase 11 — Liveness verification at top of queue (FR-05, UC-03)](#phase-11--liveness-verification-at-top-of-queue-fr-05-uc-03)
11. [Phase 12 — Provider control polish (FR-09, FR-10)](#phase-12--provider-control-polish-fr-09-fr-10)
12. [Phase 13 — Demand analytics & exports (UC-07, Scenario C)](#phase-13--demand-analytics--exports-uc-07-scenario-c)
13. [Phase 14 — Provider verification & admin governance (UC-10, UC-15, UC-16, Scenario E)](#phase-14--provider-verification--admin-governance-uc-10-uc-15-uc-16-scenario-e)
14. [Phase 15 — Offline kiosk sync protocol (NFR-02, Scenario D)](#phase-15--offline-kiosk-sync-protocol-nfr-02-scenario-d)
15. [Phase 16 — Auth depth: lockout, role routing, optional OTP (US-SYS-00)](#phase-16--auth-depth-lockout-role-routing-optional-otp-us-sys-00)
16. [Phase 17 — Hardening, performance, security, ops (NFR-01, 03, 04, 05)](#phase-17--hardening-performance-security-ops-nfr-01-03-04-05)
17. [Quality gates and engineering rules](#17-quality-gates-and-engineering-rules)
18. [Specification cross-reference](#18-specification-cross-reference)

---

## 1. Goals and principles

- **Vertical slices.** Each phase ships a runnable, testable feature with migrations + service + router + tests + docs.
- **Doc-first behavior.** When `doc.md` and the existing implementation disagree, **`doc.md` wins** unless the disagreement is purely about stack (e.g. Node vs FastAPI).
- **Additive evolution.** Prefer new tables and migrations; avoid breaking existing public APIs without a `/v2` route or feature flag.
- **Boundaries.** Routers stay thin; rules live in **service** modules; persistence in **infrastructure/repo**; pure rules in **domain** modules. Database access goes through SQLModel sessions.
- **Transactions.** All state-changing flows are explicit about transactions and locking — especially for queue and strike updates.
- **Testability first.** Every phase lists concrete unit + API + concurrency tests before it is considered done.

---

## 2. Current state inventory

### 2.1 Implemented today (matches `doc.md` MVP spine)

- **Identity**: email/password JWT, password recovery email scaffolding, role-shaped via `is_superuser` + `user_type` (`customer` / `provider` / `admin`), provider memberships (`owner` / `staff`).
- **Providers**: model + CRUD + `/discover` with Haversine distance, query filter, open/paused/private filters, simple load hints.
- **Service items**: list / create / patch under `/providers/{id}/services`.
- **Queue (FR-02, FR-03 base)**: `QueueEntry` with `source` (`remote_app` / `kiosk_walk_in`), per-service ticket numbers, transactional enqueue with row lock + partial unique index for one-active-ticket per user, walk-in registration, list, `call-next`, status patch.
- **Provider open/paused** flags block joins when set; private providers require an `access_code`.
- **Realtime**: WebSocket fan-out per `service_item_id` and per ticket, optional Redis pub/sub bridge (FR-03 sync, NFR-01 spirit).
- **Provider permissions on creation**: superuser unrestricted; `user_type=provider` may create only their own business; customers blocked.
- **Error handling**: global `ResponseValidationError` handler; private user-create endpoint validates `EmailStr`, password length, returns `409` on duplicate email.

### 2.2 Partial / drifting from `doc.md`

| Area | `doc.md` expectation | Reality | Gap |
|---|---|---|---|
| **EWT (FR-06, FR-01)** | Service-weighted moving average from completed tickets | `provider_queue_hints` uses `waiting × avg(active services baseline)` | Replace with WMA over real history per `ServiceItem` |
| **Provider control (FR-09)** | Call Next, Recall, Mark No-Show, Pause Queue | Call-next + status patch only; no first-class **recall** verb; pause exists at provider level, not per service line | Add explicit `recall` semantics; consider per-service pause |
| **Service management (FR-10)** | Create / edit / **delete** services | Only list / create / patch | Add delete (with active-ticket guard) |
| **Walk-in source (UC-04)** | Walk-in via QR scan should be tagged separately from kiosk | Only `remote_app` and `kiosk_walk_in` enums | Add `qr_scan` source (or `pwa_guest`) and an analytics-friendly tag |
| **Auth (US-SYS-00)** | OTP, 5-attempt lockout, role routing | Email/password JWT, no lockout | Add lockout & role hint; OTP optional behind a flag |
| **Provider verification (UC-10)** | Document upload + admin approval | `verification_status` field only | Add upload + workflow + admin endpoints |
| **Realtime broadcast (FR-08, UC-11)** | Provider sends mass alert to waiting users | Only system-driven events | Add provider-authored broadcast endpoint |
| **Liveness (FR-05, UC-03)** | Background GPS check at top-3 | Not present | Add reported-position channel + rules + flags |
| **Reviews (FR-11, UC-08)** | Locked until completed; mandatory accuracy boolean | Not present | New domain |
| **Penalty (FR-12)** | Strike ledger + temporary join block | Not present | New domain + enforcement at join |
| **Demand analytics (UC-07)** | Peak hours, lost demand, abandonment, exports | Not present | New event log + analytics queries + CSV |
| **Admin governance (UC-15, UC-16, Scenario E)** | Health, audit logs, suspensions | Only generic `is_active` | Add suspension semantics + audit trail |
| **Offline kiosk (NFR-02, Scenario D)** | Local IndexedDB + idempotent server sync | Not present on backend | Server-side: idempotent walk-in batch sync API |

### 2.3 Missing entirely

- Reviews (`Review` table, endpoints, aggregate rating).
- No-show strikes ledger and join-time block.
- WMA EWT engine and stored completed-ticket durations.
- Broadcast endpoint and broadcast event types.
- Notifications abstraction (push/SMS/email worker), pre-alert triggers.
- Liveness reports (position pings) and ghost-flag rules.
- `DELETE /service-items` and explicit `recall`.
- Analytics events (views, abandoned joins, missed-while-paused), reports, CSV export.
- Provider verification artifacts (file storage, approval workflow).
- Audit log subsystem and admin suspension.
- Offline kiosk batch sync endpoint.
- Auth lockout, optional OTP login.

### 2.4 Defects to fix in flight

- **EWT misnomer.** Current “estimated wait minutes” in discovery does not deserve the FR-06 label. Either rename the public field to `estimated_wait_minutes_v0` and document the heuristic, or replace once Phase 8 ships. **Fix in Phase 8.**
- **Test isolation.** `_clear_provider_and_queue_between_tests` is autouse but earlier full-suite runs showed leakage symptoms (`already have an active ticket`, `count==8` instead of `2`). Ensure that fixture order makes the clear run **after** the session-scoped `db` setup and **before** any module-scoped fixtures that create users; widen the clear to include rows created by *module*-scoped fixtures by switching offending fixtures to function scope where ordering matters. **Fix in Phase F.**
- **`UserUpdateMe.user_type`.** Currently a `Literal["provider"] | None`; clarify whether **admin → admin** is settable and whether downgrades are allowed. **Decide and codify in Phase F.**
- **`UserCreate` validator.** `is_superuser=true` silently rewrites `user_type` to `admin`. This is convenient but hides invalid input. Decide: keep with explicit docstring + tests, or reject. **Lock in Phase F.**
- **`PrivateUserCreate` route only mounted in `local`.** Good for safety; document this clearly in OpenAPI / README.
- **JWT key length warning** in tests (HMAC < 32 bytes). Use a longer test secret in CI/`.env.test` to silence and reflect production sizing.
- **WebSocket auth path** is duplicated from `deps.py`. Centralize into a shared `_user_id_from_token` to avoid drift.
- **Duplicate `from fastapi import status` import patterns** appear in some routers; lint pass.

---

## 3. Cross-cutting foundations (Phase F)

These items are prerequisites or enablers that several phases reuse. They are intentionally pulled out so feature phases stay small.

**F.1 Settings & config**
- Add settings: `STRIKE_WINDOW_DAYS`, `STRIKE_LIMIT`, `STRIKE_BLOCK_DAYS`, `EWT_HALF_LIFE_MIN`, `EWT_MIN_SAMPLES`, `LIVENESS_TOP_K`, `LIVENESS_GRACE_SECONDS`, `BROADCAST_TTL_SECONDS`, notification provider keys (kept optional).
- Validate via existing `BaseSettings` model_validators; **never** crash if optional providers are unset (degrade gracefully).

**F.2 Time + idempotency utilities**
- `werefa/shared/time.py` already has `utcnow`; add `monotonic_seq` helper if needed.
- Add `Idempotency-Key` header support and a thin `idempotency_keys` table for batch sync (Phase 15) and broadcast deduplication (Phase 9).

**F.3 Audit log**
- New `audit_log` table: `id, actor_user_id, actor_role, action, target_type, target_id, payload_json, created_at`.
- `werefa/audit/` module with a `record(...)` function used by admin/governance phases.

**F.4 Notification abstraction (no provider yet)**
- `werefa/notifications/` with a `Notifier` protocol and a `LocalLoggerNotifier` default; later phases plug Push/SMS adapters.

**F.5 Test infrastructure cleanup**
- Switch the in-memory client and any module-scoped headers fixtures to function scope where leakage is observed.
- Make `_clear_provider_and_queue_between_tests` also clear new tables introduced by later phases (parametrize via list of mappers).
- Add a `freeze_time` helper for deterministic EWT and strike windows.

**F.6 Lint & types**
- Run `ruff` + `basedpyright` clean baseline before Phase 6 starts.

**F.7 OpenAPI hygiene**
- Tag routers consistently. Each phase must update OpenAPI tags + descriptions.

**Exit criteria:** all defects in 2.4 closed, full pytest green, lint clean, audit + notifier abstractions in place but not yet used.

---

## 4. Roadmap overview

Phases run **sequentially by default** but several are independent enough to parallelize once Phase F is done.

| Phase | Theme | Spec refs | Dep |
|---|---|---|---|
| **F** | Foundations & defect fixes | NFR cross-cutting | — |
| **6** | Verified reviews | FR-11, UC-08 | F |
| **7** | Strikes + join block | FR-12, Scenario E | F |
| **8** | WMA EWT engine | FR-06, FR-01 | F |
| **9** | Provider broadcast | FR-08, UC-11 | F |
| **10** | Notifications + smart pre-alerts | FR-07 | F, 9 |
| **11** | Liveness at top-K | FR-05, UC-03 | F, 10 |
| **12** | Provider control polish | FR-09, FR-10 | F |
| **13** | Demand analytics + export | UC-07, Scenario C | F, 6, 7 |
| **14** | Verification + admin governance | UC-10, UC-15, UC-16 | F |
| **15** | Offline kiosk sync | NFR-02, Scenario D | F |
| **16** | Auth depth (lockout, role routing, optional OTP) | US-SYS-00 | F |
| **17** | Hardening, performance, security, ops | NFR-01/03/04/05 | all above |

---

## Phase 6 — Reviews and verified ratings (FR-11, UC-08)

**Goal:** A user can **only** review a provider/service after their ticket is `completed`; reviews aggregate into a provider rating; “estimate accurate?” is mandatory.

### 6.1 Domain & data model

New table `review`:
- `id (uuid pk)`
- `ticket_id (uuid fk queue_entry.id, unique)` — guarantees one review per completed visit
- `user_id (uuid fk user.id)`
- `provider_id (uuid fk provider.id, indexed)`
- `service_item_id (uuid fk service_item.id, indexed)`
- `rating (int, 1..5, check)`
- `was_estimate_accurate (bool, not null)`
- `comment (varchar 1000, nullable)`
- `created_at (timestamptz)`

New columns on `provider`:
- `ratings_count (int, default 0)`
- `ratings_sum (int, default 0)`  *(or `rating_avg numeric(4,2)` if you prefer denormalized only)*

> Storing `count` + `sum` keeps recompute O(1) on insert and avoids a full scan; `rating_avg` is computed in the API layer.

### 6.2 Rules (`werefa/reviews/domain/`)

- A review is allowed iff:
  - `ticket.user_id == current_user.id`
  - `ticket.status == 'completed'`
  - no review exists for that `ticket_id`
- `was_estimate_accurate` is **required**.

### 6.3 Service / repo

- `create_review(session, current_user, ticket_id, body)` — transactional: insert review + bump provider counters in same transaction.
- `list_reviews_for_provider(session, provider_id, limit, offset)`
- `provider_rating_summary(session, provider_id)` returns `count`, `avg`, `accuracy_rate` (= sum(was_estimate_accurate) / count).

### 6.4 Endpoints (under `/reviews`)

- `POST /tickets/{ticket_id}/reviews` — create.
- `GET /providers/{provider_id}/reviews` — paginated public list.
- `GET /providers/{provider_id}/rating` — `{ count, avg, accuracy_rate }`.

### 6.5 Migration & rollout

- Alembic revision adds `review` table + provider counter columns with default 0.
- Backfill is a no-op for new field defaults.

### 6.6 Tests

- Unit (rules): allowed/denied matrices.
- API: complete happy path; reject on non-completed ticket; reject on duplicate; reject when not the ticket owner; missing `was_estimate_accurate` is 422.
- Concurrency: two simultaneous review submissions for the same ticket end with one success + one 409.
- Aggregation: rating_avg consistent under N inserts.

### 6.7 Exit criteria

- OpenAPI surfaces all 3 endpoints; tests pass; provider discovery includes `rating_avg` (read-only) **without** breaking existing fields.

---

## Phase 7 — No-show strikes and remote-join block (FR-12)

**Goal:** Track no-shows persistently; temporarily block remote join after a configurable threshold within a rolling window. Walk-in joins are unaffected.

### 7.1 Data model

New table `user_strike`:
- `id (uuid pk)`
- `user_id (uuid fk user.id, indexed)`
- `ticket_id (uuid fk queue_entry.id)` — provenance
- `provider_id (uuid fk provider.id)`
- `kind (varchar(32))` — `no_show` (extensible later)
- `created_at (timestamptz, default now())`

Optional new column on `user`:
- `joins_blocked_until (timestamptz, nullable)` — explicit block window. Useful even when strikes are recomputed each request, for fast checks and admin overrides.

### 7.2 Rules (`werefa/strikes/domain/`)

- When a ticket transitions **into** `no_show` and `ticket.user_id IS NOT NULL`: insert a `user_strike` row.
- Block at remote-join time iff:
  - `joins_blocked_until` is in the future, **or**
  - `count(user_strike where user_id=u and created_at >= now() - INTERVAL settings.STRIKE_WINDOW_DAYS) >= settings.STRIKE_LIMIT`.
- On block trigger by counter, set `joins_blocked_until = now() + STRIKE_BLOCK_DAYS`.

### 7.3 Service / repo

- Hook into `set_ticket_status` and the “mark no-show” path so strike insertion + block evaluation are in the same DB transaction as the status change.
- Read API for self: `GET /me/strikes` returns recent strikes + `joins_blocked_until`.
- Admin overrides: `POST /admin/users/{id}/unblock` (clears `joins_blocked_until` and writes audit entry).

### 7.4 Endpoint changes

- `POST /service-items/{id}/join` returns **403** with `detail` and `joins_blocked_until` ISO timestamp when blocked.

### 7.5 Tests

- Unit: window boundary, block math, overrides.
- API: 3 strikes in 30 days → 4th remote join blocked; 31 days later allowed; admin unblock takes effect immediately; walk-in still works.
- Concurrency: simultaneous “mark no-show” and join attempt converge to a consistent block.

### 7.6 Exit criteria

- Metrics surface (logs at minimum) for `strike_recorded` and `join_blocked`.

---

## Phase 8 — Service-weighted moving-average EWT (FR-06, FR-01)

**Goal:** Replace the heuristic in `provider_queue_hints` with a **service-line WMA** based on **actual** completed durations.

### 8.1 Data

- Add `serving_started_at (timestamptz, nullable)` to `queue_entry`. (Currently we only set `completed_at`.)
- On status `waiting → serving`, set `serving_started_at = utcnow()`.
- On status `serving → completed`, the duration sample is `completed_at - serving_started_at` (clip negatives).

### 8.2 EWT algorithm

For each `service_item`:
- Collect last `N` completed tickets (e.g. last 50) ordered by `completed_at`.
- Apply **exponential weights**: `w_i = exp(-Δt_i / EWT_HALF_LIFE_MIN)`.
- `ewt_per_ticket = Σ(w_i * duration_i) / Σ(w_i)`; if `count < EWT_MIN_SAMPLES`, fall back to `service_item.avg_duration_minutes`.
- `service_ewt_minutes = ewt_per_ticket × waiting_count_for_service`.
- Aggregate provider EWT: take the **max across active services** (worst case visible) **or** sum if multiple lines block one server (configurable; default = max).

### 8.3 Service / repo

- `werefa/queue/application/ewt.py` implements `service_line_ewt(...)` and `provider_ewt(...)`; pure functions for testability.
- Replace `provider_queue_hints` consumer in `discover_providers` with the new functions; rename the public field to `estimated_wait_minutes` and document algorithm.

### 8.4 Tests

- Pure unit on synthetic samples (frozen time).
- API: discovery returns sensible numbers; cold-start fallback to baseline.
- Performance: O(N) per service line; cache last-K reads if needed.

### 8.5 Exit criteria

- `provider_queue_hints` removed or reduced to thin compatibility shim; OpenAPI reflects the new field semantics; old field kept for one release with `deprecated: true` in OpenAPI description.

---

## Phase 9 — Provider broadcast messages (FR-08, UC-11)

**Goal:** Provider/staff can push a short message to **all currently waiting/serving** tickets on a service line (or all lines of the provider).

### 9.1 Data model

New table `broadcast_message`:
- `id`, `provider_id`, `service_item_id (nullable)`, `author_user_id`, `body (varchar 500)`, `severity (varchar 16: info|warning|critical)`, `created_at`, `idempotency_key (unique nullable)`.

### 9.2 Endpoints

- `POST /providers/{provider_id}/broadcasts`
  - body: `{ service_item_id?: uuid, body: string, severity?: 'info'|'warning'|'critical' }`
  - 201 with persisted record; emits realtime event of type `broadcast_v1` to the affected service line(s) — and, when later available, triggers push (Phase 10).
- `GET /providers/{provider_id}/broadcasts?since=...`

### 9.3 Realtime contract

- Add `BroadcastEventV1` to `werefa/realtime/domain/events.py`.
- Realtime hub fans out broadcasts identically to queue events.

### 9.4 Tests

- API: only staff/owner can post; idempotency on retried post; only waiting/serving subscribers receive the event.
- Concurrency: 100-subscriber fanout under TestClient/AnyIO.

### 9.5 Exit criteria

- Documented event schema; provider portal can render messages without polling.

---

## Phase 10 — Notifications channel & smart pre-alerts (FR-07)

**Goal:** Server-driven “head to counter” notifications when ticket position or EWT crosses a threshold; provide an abstraction so push/SMS/email can be added.

### 10.1 Notifier abstraction

`werefa/notifications/notifier.py`:
- `Notifier` protocol: `async def send(channel, recipient, payload)`.
- Implementations:
  - `LoggerNotifier` (default; logs JSON).
  - `EmailNotifier` (uses existing email config).
  - `WebSocketNotifier` (sends a `notify_v1` event to that user’s ticket socket).
- `notifier_registry` resolves channel keys; first deliverable channel wins per user preferences.

### 10.2 User preferences

Add `notification_prefs JSON` on `user` (defaults: `["websocket", "email"]`). Endpoint `PATCH /users/me/notifications` to manage them.

### 10.3 Trigger rules

- After every status change or join/leave, recompute affected tickets:
  - If `position == settings.LIVENESS_TOP_K` (e.g. 3) and ticket has not been pre-alerted, mark pre-alert and send `head_to_counter`.
  - When `position == 1`, send `you_are_next`.
- Idempotency: `queue_entry.last_alert_position` column to avoid duplicates.

### 10.4 Endpoints

- `GET /me/notifications` — recent notifications log (Phase 13 also reads it).

### 10.5 Tests

- Frozen-time scenario: customer rises through positions; confirm exactly one of each alert is emitted.
- Channel selection respects preferences; degraded providers don’t crash the request flow.

### 10.6 Exit criteria

- All alert decisions are unit-tested without side effects; integration tests stub `Notifier` to assert calls.

---

## Phase 11 — Liveness verification at top of queue (FR-05, UC-03)

**Goal:** When a remote ticket reaches **top-K** (default 3), require periodic position pings from the user device; flag “ghost” candidates for the provider.

### 11.1 Data

- New table `position_ping`:
  - `id, ticket_id, lat, lng, accuracy_m, sent_at`.
- New column `queue_entry.liveness_state (varchar 16, default 'idle')` — values: `idle`, `awaiting`, `ok`, `flagged`.

### 11.2 Endpoints

- `POST /tickets/{ticket_id}/position` (auth = ticket owner) — body: `{ lat, lng, accuracy_m? }`. Stores ping; updates state to `ok`.
- `GET /tickets/{ticket_id}/liveness` — owner or staff: read current state + last ping summary.

### 11.3 Rules

- When ticket reaches top-K and is `idle`, set `awaiting`, send notification asking for an updated location.
- If no ping for `LIVENESS_GRACE_SECONDS`, set `flagged`.
- **`flagged` is not a no-show.** It is a hint for the provider; explicit “Mark No-Show” still required to assign a strike. (Avoids automated penalties.)

### 11.4 Tests

- Time-based unit tests; API: pings reset state; flagged tickets show up on staff queue list with a flag boolean.

### 11.5 Exit criteria

- No automated demotion; staff UI receives `liveness_state` over realtime to surface visually.

---

## Phase 12 — Provider control polish (FR-09, FR-10)

**Goal:** Make provider verbs match `doc.md` exactly.

- **Recall.** Add `POST /service-items/{id}/recall` that re-calls the **last completed** ticket (within a small window, e.g. 90 s). Domain rules in `queue/domain/ticket_rules.py`. Emits realtime event.
- **Service delete.** Add `DELETE /providers/{pid}/services/{sid}` with rule: 409 if any ticket in `waiting`/`serving`; otherwise hard delete (or soft delete with `deleted_at`). Document choice.
- **Per-service pause.** Allow `is_active` toggling on `service_item` to halt joins for one line without pausing the whole provider.
- **Source enum.** Add `qr_scan` to `TicketSource`. Walk-in flow gets a query parameter `source=qr_scan|kiosk` (defaults to `kiosk_walk_in` for backwards compat).

**Tests:** unit + API for each new verb; ensure existing tests stay green.

**Exit criteria:** OpenAPI exposes recall/delete; backwards compatibility on existing endpoints preserved.

---

## Phase 13 — Demand analytics & exports (UC-07, Scenario C)

**Goal:** Visible demand insights with raw events backing them and CSV export.

### 13.1 Event log

New table `demand_event`:
- `id, provider_id, service_item_id (nullable), kind, user_id (nullable), payload_json, created_at`.
- Kinds (initial): `provider_view`, `service_view`, `join_attempt_blocked_paused`, `join_attempt_blocked_strike`, `join_success`, `walk_in_success`, `abandon_after_view`, `complete`, `no_show`.

Hooks: emit events from existing services where applicable (cheap insert; allow batching later).

### 13.2 Reports

- `GET /providers/{pid}/analytics/peak-hours?from&to` → buckets by hour-of-day.
- `GET /providers/{pid}/analytics/lost-demand?from&to` → views vs joins, paused-while-attempted.
- `GET /providers/{pid}/analytics/service-times?from&to` → mean / p50 / p90 for completed tickets.
- `GET /providers/{pid}/analytics/export?from&to&format=csv` → streamed CSV.

### 13.3 Tests

- Seed events; assert aggregates; CSV smoke test.

### 13.4 Exit criteria

- Reports return in O(N) with index on `(provider_id, created_at, kind)`.

---

## Phase 14 — Provider verification & admin governance (UC-10, UC-15, UC-16, Scenario E)

**Goal:** Real verification workflow + first-class admin moderation.

### 14.1 Verification

- New table `provider_document`: `id, provider_id, kind (license|tax|other), file_url, content_type, size, uploaded_by, status (pending|approved|rejected), notes, created_at, reviewed_at`.
- File storage abstraction: local filesystem in dev, pluggable for S3/Spaces in prod.
- Endpoints:
  - `POST /providers/{pid}/documents` — multipart upload (owner/staff).
  - `GET /providers/{pid}/documents` — staff/owner/admin.
  - `POST /admin/providers/{pid}/verify` — body: `{decision: approved|rejected, notes?}`; updates `provider.verification_status` + writes audit.

### 14.2 Admin governance

- Suspension: `is_active=false` is too coarse; add `suspended_until (timestamptz)` and reason.
- `POST /admin/users/{id}/suspend` and `POST /admin/users/{id}/unsuspend`; both write audit.
- `GET /admin/audit` paginated with filters; **admin only**.
- Health endpoints: `GET /admin/health/realtime` (subscribers, redis status), `GET /admin/health/db`.

### 14.3 Tests

- Upload, list, approve/reject; suspended user cannot login (or, alternatively, gets 403 on actions); audit entries created for every governance action.

### 14.4 Exit criteria

- Verification status reflects approved documents; admin actions logged.

---

## Phase 15 — Offline kiosk sync protocol (NFR-02, Scenario D)

**Goal:** Server endpoint to accept a batch of locally created walk-in entries and reconcile them deterministically. The kiosk client owns local IndexedDB; backend just provides idempotent ingestion.

### 15.1 Endpoint

- `POST /service-items/{sid}/walk-ins/batch`
  - body: `{ entries: [{ client_id, guest_name?, joined_at_local, idempotency_key }] }`
  - per-entry behavior:
    - if `idempotency_key` already used → return existing ticket.
    - else create a `kiosk_walk_in` ticket; preserve order by `joined_at_local` but **always** allocate a new server `joined_at = utcnow()` (canonical order) — or, if you want strict client order, sort and use a monotonic sequence per service line.
- Response includes server ticket id, ticket number, status.

### 15.2 Data

- `idempotency_keys (key pk, scope, ticket_id, created_at)` (already proposed in Phase F).

### 15.3 Tests

- Replays of the same batch produce the same tickets.
- Ordering rule documented and tested.

### 15.4 Exit criteria

- Documented client contract for the kiosk app.

---

## Phase 16 — Auth depth: lockout, role routing, optional OTP (US-SYS-00)

**Goal:** Bring auth closer to `doc.md` without forcing a stack swap.

### 16.1 Lockout

- New table `login_attempt`: `id, email, ip, created_at, success`.
- After 5 failures within `LOCKOUT_WINDOW`, return 423/429 + `lock_until` until `LOCKOUT_DURATION` elapses.
- Successful login clears recent failures.

### 16.2 Role routing hint

- Login response includes `home`, derived from `user_type`/`is_superuser`, e.g. `customer_dashboard`, `provider_console`, `admin_console`. Backend does not enforce client routing; it just hints.

### 16.3 Optional OTP

- Behind `AUTH_OTP_ENABLED` flag.
- `POST /auth/otp/start` (email or phone), `POST /auth/otp/verify` returns the same `Token`.
- OTP storage table with TTL; rate-limited.

### 16.4 Tests

- Lockout boundary; OTP happy path; flag off keeps behavior identical.

### 16.5 Exit criteria

- Defaults preserve existing behavior. OTP only opt-in.

---

## Phase 17 — Hardening, performance, security, ops (NFR-01, 03, 04, 05)

- **Indexes audit**: ensure `(provider_id, created_at, kind)` on `demand_event`, `(user_id, created_at)` on `user_strike`, `(service_item_id, status)` on `queue_entry`.
- **Rate limiting**: per-IP for login + write endpoints.
- **CORS / TLS / headers**: confirm production config; document deployment.
- **Observability**: structured logs (`logger.info(event=..., **kwargs)`), `/health/live`, `/health/ready`, optional OpenTelemetry.
- **Load tests**: k6 or locust scripts targeting NFR-03 (≥1,000 concurrent joins per provider/service line).
- **Backups**: documented PG backup/restore; alembic forward-only policy.
- **Threat review**: secrets in env, no PII in logs, scrub broadcast bodies.

**Exit criteria:** A “readiness” checklist file (`ops/readiness.md`) is checked off; load tests reproducible.

---

## 17. Quality gates and engineering rules

For every phase:

1. **Migration first.** New table or column → new alembic revision. No table edits in‑place across multiple revisions.
2. **Service before router.** Implement the rule in `application/` and `domain/`; the router only validates and delegates.
3. **Tests required:**
   - Unit (`tests/components/`) for pure rules.
   - API (`tests/api/routes/`) for new endpoints.
   - Concurrency tests where state mutates under contention (joins, strikes, reviews).
4. **OpenAPI updated.** Tags + descriptions reviewed before merge.
5. **Backwards compatibility.** Existing tests must pass; deprecated fields kept for at least one phase with `description="DEPRECATED: ..."`.
6. **Lint/type green** (`ruff`, `basedpyright`).
7. **Docs.** Each phase ends with a short note appended to `docs/changelog.md` (create on first use).

---

## 18. Specification cross-reference

| Spec ref | Phase |
|---|---|
| **FR-01** Service-specific queuing | 8 (algorithm), already partly in 1 |
| **FR-02** Multi-channel entry | done; refined in 12 (qr_scan source) |
| **FR-03** Unified FIFO | done |
| **FR-04** Geofencing on join | **excluded** |
| **FR-05** Liveness | 11 |
| **FR-06** Dynamic EWT | 8 |
| **FR-07** Smart pre-alerts | 10 |
| **FR-08** Mass broadcast | 9 |
| **FR-09** Queue control (recall, no-show, pause) | 7 (no-show), 12 (recall, per-service pause) |
| **FR-10** Service CRUD inc. delete | 12 |
| **FR-11** Verified reviews | 6 |
| **FR-12** No-show penalties | 7 |
| **NFR-01** Low latency | 17 (measure), 9/10 (paths) |
| **NFR-02** Offline | 15 |
| **NFR-03** Capacity 1k concurrent | 17 |
| **NFR-04** TLS + at-rest | 17 (deployment) |
| **NFR-05** Uptime | 17 (ops) |
| **UC-00 / US-SYS-00** Auth | 16 |
| **UC-01 Search & Discovery** | done; rating in 6, EWT in 8 |
| **UC-02 Remote join** | done; refinements in 7 (block) |
| **UC-03 Liveness** | 11 |
| **UC-04 Hybrid walk-in** | done; refined in 12 + 15 |
| **UC-05 Call next** | done |
| **UC-06 Mark no-show** | done; persistence/penalty in 7 |
| **UC-07 Demand analytics** | 13 |
| **UC-08 Verified review** | 6 |
| **UC-09 Configure services** | done; delete in 12 |
| **UC-10 Verification** | 14 |
| **UC-11 Broadcast** | 9 |
| **UC-12 QR / deep link** | 12 (source tag); client work mostly external |
| **UC-13 Pause queue** | done at provider level; per-service in 12 |
| **UC-14 Geofence radius config** | already on `Provider`; **enforcement on join is excluded** |
| **UC-15 System health dashboard** | 14 |
| **UC-16 Manage user accounts** | 14 |

---

## Appendix A — Open product decisions

1. **Per-provider EWT aggregation:** `max(service_line_ewt)` (default) vs `sum`. Revisit after seeing real data.
2. **Recall window:** 90 s default; configurable.
3. **Strike scope:** global per user (default) vs per provider. Default global is simpler and matches Scenario E.
4. **Soft vs hard delete for services:** soft delete recommended to preserve analytics history.
5. **Reviews edit window:** disallowed by default; consider 24 h window only if product demands it.
6. **Notification provider:** start with WebSocket + email; SMS/Push behind feature flags so no provider lock-in until needed.

---

## Appendix B — Cut list (explicit non-goals)

- **FR-04 join-time geofence.** Out per direction.
- **PWA UI** under Scenario F is a client concern; backend only needs the same `qr_scan` source tag from Phase 12.
- **Phone OTP as the only login.** Treated as optional in Phase 16.
- **Hardware token dispenser integration.** Not in this backend.
