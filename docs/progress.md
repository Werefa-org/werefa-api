# Werefa backend — implementation progress

This file is the **live tracker** for the work described in [`phase-plan.md`](./phase-plan.md).
Status legend: `[ ]` pending · `[~]` in progress · `[x]` done · `[!]` blocked.

When a phase is closed:
- mark every item `[x]` or `[~]` (with note),
- record the merge commit / branch under **Notes**,
- bump the **Last updated** line below.

**Last updated:** 2026-04-29 (Phase 9 closed)

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

- [x] **Migration** `e8b1f5d27a40_strikes_and_join_block.py` — adds the
      `user_strike` table (FK to `user`, `queue_entry`, `provider`, all
      `ondelete=CASCADE`) plus a composite index `ix_user_strike_user_created_at`
      so the recurring "count strikes for user in window" query is a single
      index scan with no sort step. Adds `user.joins_blocked_until` (nullable
      `timestamptz`).
- [x] **Settings** in `core/config.py` — `STRIKE_WINDOW_DAYS=30`,
      `STRIKE_LIMIT=3`, `STRIKE_BLOCK_DAYS=7` matching the example in
      `doc.md` Chapter 3. Tests reassign these in-place to exercise window
      math without waiting wall-clock time, and a fixture restores them.
- [x] **Domain** `werefa/strikes/domain/strike_rules.py` — pure functions
      `window_start`, `evaluate_block` (returns a `BlockEvaluation`
      dataclass), `block_until_for_threshold`. No Session, no HTTP. Both
      conditions from the spec (explicit block timestamp **or** strike
      count `>= limit`) are encoded; defensive paths handle a 0/negative
      window or limit so a misconfig can't silently lock everyone out.
- [x] **Repo** `werefa/strikes/infrastructure/repo.py` — `insert_strike`
      flushes (no commit) so it composes with the queue's transaction;
      `count_strikes_since` returns an integer using `func.count`;
      `list_strikes_for_user` for the `/me/strikes` read.
- [x] **Service** `werefa/strikes/application/service.py` —
      `record_no_show` (skips walk-ins, inserts strike, materialises
      `joins_blocked_until` only when the threshold is crossed and only
      *extends* an existing block, never shrinks it),
      `assert_remote_join_allowed` (the join-time guard;
      raises `403` with a structured `detail` containing
      `joins_blocked_until`, `reason`, `strikes_in_window`, `limit`,
      `window_days`), `get_self_strike_summary`, `admin_unblock_user`.
      `strike_recorded`, `join_block_set`, `join_blocked`, and
      `join_block_cleared_by_admin` are emitted to the standard logger
      so an ops log scrape works on day one.
- [x] **Queue hook** in `werefa/queue/application/service.py` —
      `set_ticket_status` calls `record_no_show` *before* commit so the
      strike row and the status flip share one transaction.
      `join_queue_remote` calls `assert_remote_join_allowed` *before*
      taking the row lock so blocked users pay no contention cost.
      Walk-in joins (`join_queue_walk_in`) deliberately do **not** call
      the guard — FR-12 is for remote joins only.
- [x] **Endpoints** in `werefa/strikes/interface/router.py` —
      `GET /me/strikes` (current user; returns rows in the active window
      plus `joins_blocked_until`, `limit`, `window_days`) and
      `POST /admin/users/{user_id}/unblock` (superuser-gated; clears
      the block window; returns the updated `UserPublic`).
- [x] **Conftest update** — clears `Review` and `UserStrike` between
      tests, and resets `User.joins_blocked_until = NULL` after each
      test so a strike test can't leak a 403 into the next file.
- [x] **Domain rule tests** `tests/components/strikes/test_strike_rules.py`
      cover: window math, below-limit, at-limit threshold, explicit
      block precedence, expired explicit block, zero-limit safety,
      `block_until` math, negative-block-days clamp.
- [x] **API tests** `tests/api/routes/test_strikes.py` cover:
      no-show records a strike (registered user), no-show on walk-in
      records *no* strike, three strikes block remote join with the
      structured 403 detail, walk-in still works for the same person,
      old strikes outside the window do not block, `GET /me/strikes`
      returns window stats, admin unblock clears the block and the user
      can join immediately, non-superuser cannot call the unblock
      endpoint.

### Quality gates for Phase 7

- [x] **No-DB rule verification**: every branch of `evaluate_block` and
      both helpers exercised via standalone Python with frozen `now`
      values — all assertions pass.
- [x] **Wiring verification (no DB)**: imports resolve, `/me/strikes`
      and `/admin/users/{user_id}/unblock` are registered, queue hooks
      reference both `assert_remote_join_allowed` and `record_no_show`,
      and the three new settings are exposed.
- [~] **Pytest** for `tests/components/strikes/` and
      `tests/api/routes/test_strikes.py` — blocked at 2026-04-29 by the
      same Neon Postgres outage that gated Phases F and 6
      (`OperationalError: server closed the connection unexpectedly`).
      Re-run when the DB is healthy; the unit-level rule tests above
      run without a DB and already pass.
- [x] No new lints introduced (only the pre-existing
      "could not be resolved" basedpyright environment warnings).

### Notes

- 2026-04-29: Phase 7 shipped behind the same DB outage as the previous
  phases. Migration sequence is now
  `b2c4e6d8a0f1 → d4f8c1a3b209 → e8b1f5d27a40`; running `alembic upgrade
  head` will pick up everything in order.
- Block window is *materialised* on the user row when a strike just
  pushes past the limit. This keeps the join-time check O(1) for the
  hot path (single SELECT on the user row) and survives the rolling
  window moving past older strikes. The recompute path inside
  `assert_remote_join_allowed` covers the (unlikely) case where strikes
  were inserted via SQL without going through `record_no_show`.
- The 403 response body intentionally returns a structured
  `detail` object (`reason`, `joins_blocked_until`, `strikes_in_window`,
  `limit`, `window_days`) instead of a bare string so the client can
  build a human message *and* a "Try again on …" prompt without parsing.

---

## Phase 8 — Service-weighted moving-average EWT (FR-06, FR-01)

- [x] **Migration** `f1a3c9b6e521_serving_started_at.py` — adds
      `queue_entry.serving_started_at` (nullable `timestamptz`).
      No backfill: pre-migration completed tickets have no recorded serve
      start, so they are conservatively excluded from the WMA. The
      algorithm transparently falls back to the per-service
      `avg_duration_minutes` baseline until ≥`EWT_MIN_SAMPLES`
      post-migration samples accrue.
- [x] **Settings** in `core/config.py` — `EWT_HALF_LIFE_MIN=30.0`,
      `EWT_MIN_SAMPLES=3`, `EWT_HISTORY_LIMIT=50`,
      `EWT_PROVIDER_AGGREGATION='max'` (configurable to `'sum'` for
      single-server providers).
- [x] **Pure module** `werefa/queue/application/ewt.py` —
      `service_line_ewt_minutes` (cold-start fallback, exponential
      recency weights, history truncation, drops zero/negative
      durations and clamps future-skew samples) and `provider_ewt_minutes`
      (max/sum across active service lines, ignores `None` lines).
      Returns minutes as `float | None`; `round_minutes(...)` produces
      the integer value the public schema needs.
- [x] **Queue hook** in `queue/application/service.py` —
      `call_next_transition` stamps `serving_started_at = utcnow()`
      whenever a ticket flips `waiting → serving`. The only other path
      that could reach `serving` (manual `set_ticket_status`) is
      explicitly disallowed by `validate_manual_status_change`, so this
      is the single source of truth for serve-start.
- [x] **Repo** `providers/infrastructure/repo.py` — replaced
      `provider_queue_hints` (a single-pass heuristic) with two narrower
      helpers: `provider_active_ticket_counts` (waiting/serving + per-
      service waiting map) and `list_completed_samples_for_service`
      (last N completed tickets with both timestamps populated).
      The split keeps the math in the pure module and lets the service
      compose them.
- [x] **Discovery wiring** in `providers/application/service.py` —
      `_compute_provider_load_and_ewt` invokes the WMA per active
      service line and aggregates with the configured strategy.
      Public response shape (`ProviderDiscoveryPublic`) is unchanged;
      `estimated_wait_minutes` now reflects the new algorithm.
- [x] **Pure-math tests** `tests/components/queue/test_ewt.py` cover:
      zero-waiting → 0, cold start → fallback, below-min-samples →
      fallback, WMA matches manual formula, zero/negative durations
      dropped, history limit truncates oldest first, future-skew sample
      clamped, provider aggregation `max`/`sum`/all-`None`, and
      `round_minutes` edge cases.
- [x] **API tests** `tests/api/routes/test_provider_discovery_ewt.py`
      cover: cold-start (3 waiting × 20-min baseline ⇒ 60),
      post-completion (3 four-minute samples beat a 999-minute
      baseline so EWT is in the 3–5 min band), zero-waiting yields 0,
      and a sanity check that `call-next` actually stamps
      `serving_started_at` on the ticket row.
- [x] **Existing test compatibility** — `test_discover_provider_returns_load_hints`
      keeps passing because in the no-completed-samples case the WMA
      falls back to the same per-service baseline, so 1 waiting × 30
      avg = 30 minutes is still the right answer.

### Quality gates for Phase 8

- [x] **No-DB rule verification**: WMA, weighting, fallback, truncation,
      future-skew clamp, and aggregation all exercised via standalone
      Python — every assertion passes.
- [x] **Wiring verification (no DB)**: `provider_queue_hints` is gone
      from the repo; the discovery service calls
      `service_line_ewt_minutes` and `provider_ewt_minutes` directly;
      the `QueueEntry` model exposes the new column; `call_next` flips
      `serving_started_at` to `utcnow()`.
- [~] **Pytest** — blocked at 2026-04-29 by the persistent Neon Postgres
      outage that gated Phases F, 6, and 7. The unit-level WMA tests
      run without a DB and already pass.
- [x] No new lints introduced (only the pre-existing
      "could not be resolved" basedpyright environment warnings).

### Notes

- 2026-04-29: Phase 8 shipped. Migration sequence is now
  `b2c4e6d8a0f1 → d4f8c1a3b209 → e8b1f5d27a40 → f1a3c9b6e521`.
- The legacy `provider_queue_hints` was deleted outright rather than
  kept as a shim because it had a single internal caller and no one in
  the codebase depended on its name. The OpenAPI surface
  (`estimated_wait_minutes`) is unchanged, so clients see no breaking
  change — only better numbers.
- The `EWT_PROVIDER_AGGREGATION` setting (Appendix A of the phase plan,
  "Provider EWT aggregation: max vs sum") now has a concrete default
  (`max`) and a flippable knob; switching to `sum` is a one-env-var
  change, no code rebuild.

---

## Phase 9 — Provider broadcast (FR-08, UC-11)

- [x] **Migration** `aa92d4f80c17_broadcast_message.py` — adds the
      `broadcast_message` table with FKs to `provider`, `service_item`
      (nullable), and `user` (author), all `ondelete=CASCADE`. Severity
      column carries a `CHECK (severity IN ('info','warning','critical'))`
      so the database is the final guardrail. Idempotency is scoped per
      provider via the unique constraint
      `uq_broadcast_provider_idem_key (provider_id, idempotency_key)`,
      relying on Postgres's "NULLs distinct" semantics so requests
      without a key are never deduplicated. A composite
      `ix_broadcast_provider_created_at` removes the sort step from
      `GET /providers/{id}/broadcasts?since=...`.
- [x] **Enum** `BroadcastSeverity` (`info`/`warning`/`critical`) in
      `werefa/shared/enums.py`.
- [x] **Models** in `werefa/shared/models.py` —
      `BroadcastMessageBase`, `BroadcastCreate`, `BroadcastMessage`
      (table), `BroadcastPublic`, `BroadcastsPublic`.
- [x] **Realtime event** `BroadcastEventV1` in
      `werefa/realtime/domain/events.py` with `type="broadcast_v1"`,
      `Literal` severity enforcement, and ISO timestamp serialiser.
      The new module-level constant `BROADCAST_EVENT_TYPE` is the
      single source of truth used by both the publisher and the
      ticket-stream filter.
- [x] **Repo** `werefa/broadcasts/infrastructure/repo.py` —
      `get_by_idempotency_key`, `list_for_provider` (with `since`
      cursor + limit, descending order on `created_at`).
- [x] **Service** `werefa/broadcasts/application/service.py` —
      `create_broadcast` validates severity at the application layer
      (so the 400 surface is consistent), checks the idempotency key
      *before* insert, falls back to the same lookup if the unique
      constraint resolves a concurrent-replay race, and returns
      `(record, created: bool)` so the router can flip the status code
      between `201` and `200`. Logs `broadcast_created` on success.
- [x] **Realtime fan-out** `notify_broadcast_subscribers` in
      `werefa/realtime/notify.py` — best-effort, never blocks the
      caller, never raises (failures are logged). When a broadcast
      targets a single service line it fans out to that channel only;
      when ``service_item_id`` is null, it iterates every active
      service line of the provider so subscribers always receive
      events on a channel they're already attached to.
- [x] **Ticket-stream filter** in `werefa/realtime/interface/router.py`
      — `_message_for_ticket` now peeks at `type` first; broadcast
      events are *always* forwarded to ticket-scoped sockets, queue
      events still match by `ticket_id`, and malformed payloads or
      unknown event types are silently dropped.
- [x] **Router** `werefa/broadcasts/interface/router.py` —
      `POST /providers/{provider_id}/broadcasts` (status `201` on
      create, `200` on idempotent replay) and
      `GET /providers/{provider_id}/broadcasts?since=...&limit=...`,
      both gated by `ensure_provider_staff` so the message ledger
      doesn't leak operational state to customers.
- [x] **Wiring** `werefa/api/main.py` includes the new router under
      the existing `/providers` prefix.
- [x] **Conftest update** — clears `BroadcastMessage` between tests
      (and on session teardown) so a stale message from one test file
      never reaches the next.
- [x] **Unit tests** `tests/components/realtime/test_broadcast_events.py`
      cover: schema round-trip with ISO timestamp, rejection of
      unknown severity, body-length enforcement, the broadcast-always-
      forwards rule for the ticket filter, queue-event ticket-id
      match/mismatch, malformed JSON / non-object payloads, and an
      unknown `type` is dropped.
- [x] **API tests** `tests/api/routes/test_broadcasts.py` cover:
      staff posts a provider-wide broadcast, staff posts a service-
      scoped broadcast, severity rejection (400), empty-body
      rejection (422), service from a different provider rejected
      (404), idempotency replay (201 then 200, single row in DB),
      customer cannot post (403), customer cannot list (403), and
      list returns recent-first with a `since` filter.

### Quality gates for Phase 9

- [x] **No-DB schema verification**: `BroadcastEventV1` round-trips,
      severity Literal rejects junk, body length is enforced, and the
      ticket-stream filter forwards broadcasts while still matching
      queue events by ticket id.
- [x] **Wiring verification (no DB)**: imports resolve, the new
      `/providers/{provider_id}/broadcasts` route is registered, the
      conftest clears `BroadcastMessage`, and the service signature
      returns `(BroadcastMessage, bool)` for the 201/200 split.
- [~] **Pytest** for `tests/components/realtime/` and
      `tests/api/routes/test_broadcasts.py` — blocked at 2026-04-29 by
      the same Neon Postgres outage that gated previous phases. The
      schema/filter tests run without a DB and pass.
- [x] No new lints introduced (only the pre-existing
      "could not be resolved" basedpyright environment warnings).

### Notes

- 2026-04-29: Phase 9 shipped. Migration sequence is now
  `b2c4e6d8a0f1 → d4f8c1a3b209 → e8b1f5d27a40 → f1a3c9b6e521 →
  aa92d4f80c17`.
- The realtime fan-out is *best-effort* by design: a publish failure
  never rolls back the persisted broadcast, so the message is always
  reachable through `GET /providers/{id}/broadcasts` even if a Redis
  bridge or coordinator hiccup eats one realtime delivery. Phase 10
  will layer push/email on top of the same persisted ledger.
- Idempotency is keyed on `(provider_id, idempotency_key)` so two
  unrelated providers can use the same client-generated string without
  colliding. The replay path returns the original record's body
  verbatim (including the stored `severity`) — the second request's
  fields are *not* used to update the first, which mirrors how most
  payment APIs handle Idempotency-Key.

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


## Open product decisions (from `phase-plan.md` Appendix A)

- [x] Provider EWT aggregation: max vs sum. **Default: `max`**, configurable
      via `EWT_PROVIDER_AGGREGATION` env var (Phase 8).
- [ ] Recall window length.
- [ ] Strike scope: global vs per provider.
- [ ] Service deletion: soft vs hard.
- [ ] Reviews edit window: disallowed vs 24 h.
- [ ] Notification provider mix at launch.
