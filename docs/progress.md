# Werefa backend — implementation progress

This file is the **live tracker** for the work described in [`phase-plan.md`](./phase-plan.md).
Status legend: `[ ]` pending · `[~]` in progress · `[x]` done · `[!]` blocked.

When a phase is closed:
- mark every item `[x]` or `[~]` (with note),
- record the merge commit / branch under **Notes**,
- bump the **Last updated** line below.

**Last updated:** 2026-04-29

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

- [ ] Migration: add `review` table, `provider.ratings_count`, `provider.ratings_sum`.
- [ ] Domain: review-allowed rules in `werefa/reviews/domain/`.
- [ ] Service / repo: `create_review`, `list_reviews_for_provider`, `provider_rating_summary`.
- [ ] Endpoints: `POST /tickets/{id}/reviews`, `GET /providers/{id}/reviews`, `GET /providers/{id}/rating`.
- [ ] Tests: rules unit, API happy path, duplicate rejection, ownership, concurrency.
- [ ] Discovery exposes `rating_avg` (read-only).

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
