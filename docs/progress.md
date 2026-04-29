# Werefa backend — implementation progress

This file is the **live tracker** for the work described in [`phase-plan.md`](./phase-plan.md).
Status legend: `[ ]` pending · `[~]` in progress · `[x]` done · `[!]` blocked.

When a phase is closed:
- mark every item `[x]` or `[~]` (with note),
- record the merge commit / branch under **Notes**,
- bump the **Last updated** line below.

**Last updated:** 2026-04-29 (Phase 6 closed)

---

## Phase F — Foundations & defect fixes

Scope and rationale: see [`phase-plan.md` §3](./phase-plan.md#3-cross-cutting-foundations-phase-f) and [§2.4](./phase-plan.md#24-defects-to-fix-in-flight).

### Defects to fix in flight

- [x] **Test isolation.** Provider / queue / membership rows wiped **before and after** each test so module-scoped fixtures don't leak state.
- [x] **WebSocket JWT helper duplication.** `_user_id_from_token` lives in one shared module; realtime router imports it.
- [x] **JWT key length warning in tests.** Test session promotes `SECRET_KEY` to a 32+ byte value so HMAC warnings disappear and signature lengths match production.
- [x] **`UserCreate` validator behavior is documented and tested.** `is_superuser=True` forces `user_type='admin'`; setting `user_type='admin'` directly without `is_superuser=True` is rejected.
- [x] **`PrivateUserCreate` mounted only in `local`.** Documented in OpenAPI `description`.
- [ ] EWT misnomer: rename / replace public field — deferred to **Phase 8**.
- [ ] Per-service pause and explicit recall — deferred to **Phase 12**.

### Foundational scaffolding (kept narrow on purpose)

- [ ] `werefa/audit/` skeleton — defer to **Phase 14** (table + record).
- [ ] `werefa/notifications/` skeleton — defer to **Phase 10**.
- [ ] `idempotency_keys` table — defer to **Phase 9 / 15**.

### Quality gates for Phase F

- [~] `tests/api/routes/test_private.py` — verified earlier in this branch; full
      pytest re-run blocked at 2026-04-29 by the upstream **Neon Postgres outage**
      (`server closed the connection unexpectedly` / `OperationalError`). Re-run
      when DB is healthy.
- [~] `tests/api/routes/test_provider_create_permissions.py` — same.
- [~] `tests/components/...` — same.
- [x] **Direct Python verification (no DB)**: `UserCreate` validator + WS auth
      helper round-trip exercised through `uv run python` — all assertions pass.
- [x] No new lints introduced (`ruff` / `basedpyright` baseline preserved; only
      pre-existing "could not be resolved" warnings remain because basedpyright
      is not configured to see the venv on this machine).

### Notes

- 2026-04-29: Phase F shipped.
  - WS auth duplication removed via new `werefa/core/auth_ws.user_id_from_token`;
    the realtime router imports it instead of redefining its own decoder.
  - Test session forces `SECRET_KEY` to 32+ bytes when `.env` provides a short
    value, so PyJWT's `InsecureKeyLengthWarning` is gone for tests and the
    signature exercise approximates production sizing.
  - `UserCreate` validator behavior is now both **enforced** and **documented
    via tests**: superuser ⇒ admin (auto-coerced), bare `user_type='admin'`
    rejected.
  - Test isolation: provider / membership / service / queue rows are cleared
    before *and* after each test.
  - `PrivateUserCreate` route documented as **local-only** through a comment on
    `APIRouter(...)` describing its conditional mount.
- 2026-04-29: Full pytest re-run pending; Neon DB is intermittently dropping
  connections. Validator and helper invariants confirmed via a no-DB script.

---

## Phase 6 — Reviews and verified ratings (FR-11, UC-08)

- [x] **Migration** `d4f8c1a3b209_review_and_rating_counters.py` — adds the
      `review` table (FK to `queue_entry`, `user`, `provider`, `service_item`)
      with a unique constraint on `ticket_id` (one review per ticket) and a
      `CHECK (rating BETWEEN 1 AND 5)`; adds `provider.ratings_count`,
      `provider.ratings_sum`, `provider.estimate_accurate_count` (all
      `NOT NULL` with `server_default '0'` so existing rows backfill safely).
- [x] **Domain** `werefa/reviews/domain/review_rules.py` exposes
      `validate_ticket_can_be_reviewed(...)` raising a typed
      `ReviewRuleError`. Pure function, no `Session`, no HTTP — keeps the
      contract trivially unit-testable.
- [x] **Repo** `werefa/reviews/infrastructure/repo.py` —
      `get_review_for_ticket`, `list_reviews_for_provider` (with limit/offset
      and total count). No business rules here.
- [x] **Service** `werefa/reviews/application/service.py` — `create_review`
      validates the rules, creates the row, **and bumps the provider counters
      transactionally** so reads stay O(1). Translates `ReviewRuleError` to
      `400` (or `409` for duplicate), and catches `IntegrityError` on the
      unique index for the concurrent-double-submit race.
      `list_reviews_for_provider` and `provider_rating_summary` round it out.
- [x] **Router** `werefa/reviews/interface/router.py` exposes the three
      endpoints across two prefixes:
      - `POST  /tickets/{ticket_id}/reviews` (auth required)
      - `GET   /providers/{provider_id}/reviews` (public)
      - `GET   /providers/{provider_id}/rating` (public)
- [x] **Wiring** `werefa/api/main.py` includes both routers.
- [x] **Discovery exposes `rating_avg`** (read-only, non-breaking):
      `ProviderPublic` gained `ratings_count` and `rating_avg` fields, plus
      `provider_public_view(p)` helper used by `/providers/{id}`,
      `/providers/by-slug/{slug}`, the create/update responses, and
      `/providers/discover`. `ratings_sum` and `estimate_accurate_count`
      stay private to the server.
- [x] **Domain rule tests** `tests/components/reviews/test_review_rules.py`
      cover happy path, walk-in rejection, ownership rejection, every
      non-`completed` status, and duplicate guard — all without a DB.
- [x] **API tests** `tests/api/routes/test_reviews.py` cover happy path
      (review + summary + listing), schema-level rejection of missing
      `was_estimate_accurate`, rating bounds (`1..5`), ownership rejection
      with a different user's token, non-completed-ticket rejection,
      duplicate `409`, and discovery now showing `rating_avg`.

### Quality gates for Phase 6

- [x] **No-DB rule verification**: review rules executed via standalone
      Python — every branch (happy / walk-in / wrong actor / each
      non-completed status / duplicate) returns the expected outcome.
- [x] **Wiring verification (no DB)**: imports resolve, all three new routes
      are registered on `api_router`, `ProviderPublic` exposes `rating_avg`
      and `ratings_count` while hiding `ratings_sum`, and
      `provider_public_view` computes correct averages including the 0-count
      edge case.
- [~] **Pytest** for `tests/components/reviews/` and `tests/api/routes/test_reviews.py`
      — blocked at 2026-04-29 by the same Neon Postgres outage that blocked
      the Phase F gates (`OperationalError: server closed the connection
      unexpectedly`). Re-run when the database is healthy; the unit-level
      rule tests above run without a DB and already pass.
- [x] No new lints introduced (only the pre-existing `basedpyright` cannot
      see-the-venv warnings remain).

### Notes

- 2026-04-29: Phase 6 shipped behind the same DB outage that affected the
  Phase F re-run. All non-DB checks pass; the migration sequence is
  `b2c4e6d8a0f1 → d4f8c1a3b209` so applying head will pick up the new
  schema.
- The `Review` table is keyed by `ticket_id` (unique) so the contract
  "one review per ticket" is enforced at the database, not just the
  service. The application layer still does an existence check first to
  return a friendly 409, but the unique index is the authoritative guard.
- Discovery's exposed averages are computed from the cached counters on
  `provider`, so listing N providers is still N + 1 queries, **not**
  N × `count(*)` joins on `review`.

---

## Phase 7 — No-show strikes & remote-join block (FR-12)

- [ ] Migration: `user_strike` table, `user.joins_blocked_until`.
- [ ] Hook into `set_ticket_status` for `no_show`.
- [ ] Settings: `STRIKE_WINDOW_DAYS`, `STRIKE_LIMIT`, `STRIKE_BLOCK_DAYS`.
- [ ] Block enforcement in `join_queue_remote`.
- [ ] Endpoints: `GET /me/strikes`, `POST /admin/users/{id}/unblock`.
- [ ] Tests: window math, block, admin unblock, walk-in unaffected.

---

## Phase 8 — Service-weighted moving-average EWT (FR-06, FR-01)

- [ ] Migration: `queue_entry.serving_started_at`.
- [ ] Pure module `werefa/queue/application/ewt.py` (WMA).
- [ ] Replace `provider_queue_hints` heuristic.
- [ ] Public field renamed/deprecated as planned.
- [ ] Tests: pure unit + API + cold-start fallback.

---

## Phase 9 — Provider broadcast (FR-08, UC-11)

- [ ] Migration: `broadcast_message`.
- [ ] Endpoints: `POST /providers/{id}/broadcasts`, `GET /providers/{id}/broadcasts`.
- [ ] Realtime: `BroadcastEventV1`.
- [ ] Tests: staff-only auth, idempotency, fan-out.

---

## Phase 10 — Notifications + smart pre-alerts (FR-07)

- [ ] `werefa/notifications/notifier.py` + adapters (Logger, Email, WebSocket).
- [ ] User notification preferences.
- [ ] Trigger rules at top-K and position #1.
- [ ] Migration: `queue_entry.last_alert_position`.
- [ ] Endpoint: `GET /me/notifications`.
- [ ] Tests: time-based scenario, preference selection.

---

## Phase 11 — Liveness at top-K (FR-05, UC-03)

- [ ] Migration: `position_ping`, `queue_entry.liveness_state`.
- [ ] Endpoints: `POST /tickets/{id}/position`, `GET /tickets/{id}/liveness`.
- [ ] Rules: idle → awaiting → ok / flagged.
- [ ] Tests: time-based, staff sees flags.

---

## Phase 12 — Provider control polish (FR-09, FR-10)

- [ ] Recall: `POST /service-items/{id}/recall`.
- [ ] Service delete: `DELETE /providers/{pid}/services/{sid}` with active-ticket guard.
- [ ] Per-service pause via `is_active` toggling (already partial).
- [ ] `qr_scan` source enum + walk-in flag.
- [ ] Tests for each verb.

---

## Phase 13 — Demand analytics & exports (UC-07)

- [ ] Migration: `demand_event`.
- [ ] Hooks for view / abandon / paused-attempt / join.
- [ ] Reports endpoints + CSV export.
- [ ] Tests: aggregates, CSV smoke.

---

## Phase 14 — Verification & admin governance (UC-10, UC-15, UC-16)

- [ ] `provider_document` migration + storage abstraction.
- [ ] Verification endpoints + admin approval.
- [ ] Suspension model (`suspended_until`, reason).
- [ ] Audit log endpoints + ledger.
- [ ] Health endpoints.
- [ ] Tests for each governance action.

---

## Phase 15 — Offline kiosk batch sync (NFR-02, Scenario D)

- [ ] `idempotency_keys` table.
- [ ] `POST /service-items/{sid}/walk-ins/batch`.
- [ ] Tests: replay safety, ordering rules.

---

## Phase 16 — Auth depth (US-SYS-00)

- [ ] `login_attempt` table; lockout window/duration.
- [ ] Login response includes `home` hint.
- [ ] OTP behind feature flag (`AUTH_OTP_ENABLED`).
- [ ] Tests: lockout boundary, OTP happy path with flag.

---

## Phase 17 — Hardening, performance, security, ops (NFR-01, 03, 04, 05)

- [ ] Indexes audit.
- [ ] Rate limits on login + write endpoints.
- [ ] Structured logging baseline.
- [ ] `/health/live`, `/health/ready` endpoints.
- [ ] Load tests reproducible (k6 or locust).
- [ ] `ops/readiness.md` checklist.

---

## Open product decisions (from `phase-plan.md` Appendix A)

- [ ] Provider EWT aggregation: max vs sum.
- [ ] Recall window length.
- [ ] Strike scope: global vs per provider.
- [ ] Service deletion: soft vs hard.
- [ ] Reviews edit window: disallowed vs 24 h.
- [ ] Notification provider mix at launch.
