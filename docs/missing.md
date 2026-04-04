# Werefa backend — missing & partial scope

This document tracks **backend** gaps versus `docs/doc.md` (FR/UC/NFR) and internal product expectations. Use it as the implementation backlog.

**Last implementation pass (2026-05):** QR invites, kiosk batch sync, demand events + admin CSV, KYC document upload/list/download, admin health + user suspend/search, reject reasons, login lockout + OTP stub, push/sms notifier stubs, notification `read_at`.

**Status legend:** Missing | Partial | Spec mismatch (code exists but behavior does not match the PDF)
---

## Critical missing (no or negligible backend support)

| ID / area | Spec reference | What’s missing |
|-----------|----------------|----------------|
| ~~**Join-time geofence**~~ | ~~FR-04, UC-02, UC-14~~ | **Done:** Remote join accepts optional `latitude` / `longitude` on `QueueJoin`. When `Provider.join_radius_m` is set, coordinates are required and distance (Haversine via `provider_repo.distance_meters`) must be ≤ radius; walk-ins unchanged. |
| ~~**Liveness / presence**~~ | ~~FR-05, UC-03~~ | **Done (MVP):** `queue_entry.liveness_state` + `position_ping`; `POST …/tickets/{id}/position`, `GET …/tickets/{id}/liveness`; top-`LIVENESS_TOP_K` remote waits enter `awaiting`, `liveness_ping_request` notification, grace `LIVENESS_GRACE_SECONDS`, then `flagged` (hint only — no auto strike); sync runs from smart-alert eval + lazy read. |
| ~~**QR / deep link entry**~~ | ~~FR-02, UC-12~~ | **Done:** `TicketSource.qr_scan`; staff `POST /service-items/{id}/join-invites`; public `GET /join-invites/resolve`; remote join accepts `invite_token` on `QueueJoin` (satisfies private access in place of access code). |
| ~~**Offline kiosk sync**~~ | ~~NFR-02, Scenario D~~ | **Done:** `POST /service-items/{id}/kiosk-sync-batch` with `idempotency_key` + `walk_ins[]`; `kiosk_sync_batch` table replays stored ticket snapshot. |
| ~~**Recall customer**~~ | ~~FR-09~~ | **Done:** `POST /service-items/{id}/recall` — staff-only; most recent **completed** ticket on the line within `RECALL_COMPLETED_WINDOW_SECONDS` (default 90s) returns to **serving**; 409 if someone is already serving, if a review exists, or if the customer already has another active ticket. |
| ~~**Delete service**~~ | ~~FR-10, UC-09~~ | **Done:** `DELETE /providers/{pid}/services/{sid}` — 204 when no `waiting`/`serving` tickets; 409 otherwise; staff-only. |
| ~~**Demand analytics**~~ | ~~UC-07~~ | **Done (MVP):** `demand_event` log; hooks on join/cancel/batch; `POST /analytics/demand-events`; admin `GET /admin/analytics/demand-summary` + `GET /admin/analytics/demand.csv`. |
| ~~**Lost demand / abandonment**~~ | ~~Scenario C, UC-07~~ | **Done (MVP):** `queue_abandon` events on voluntary customer cancel; client may emit `service_view` via demand ingest. |
| ~~**Admin system health API**~~ | ~~UC-15~~ | **Done (MVP):** Superuser `GET /admin/system/health` — DB ping, Redis flag, in-process WebSocket subscriber counts. |
| ~~**Admin user governance**~~ | ~~UC-16, Scenario E~~ | **Done (MVP):** `GET /admin/users/search?q=` (phone substring); `POST /admin/users/{id}/suspend` + `unsuspend`; `admin_audit_log` rows on provider verify/reject and user suspend. |
| ~~**KYC documents**~~ | ~~UC-10~~ | **Done (MVP):** `provider_document` + `POST /admin/providers/{id}/documents` (multipart); staff `GET /providers/{id}/documents` + file download. |
| ~~**Reject reason persistence**~~ | ~~UC-10 acceptance~~ | **Done:** `POST /admin/providers/{id}/reject` accepts `{ "reason": "…" }`; `provider.last_rejection_reason`; surfaced on staff/`me` provider payloads. |
| ~~**OTP / lockout / auth depth**~~ | ~~US-SYS-00~~ | **Done (MVP):** `failed_login_count` / `locked_until`; `POST /login/otp/request` + `/login/otp/verify` (email code stub — logs code in local env); suspended users blocked at login and JWT deps. |
| **Real push / SMS** | Narratives FR-07, UC-05 | **Partial:** `NotificationChannel.push` / `sms` + registry entries; **stub** delivery when `PUSH_DELIVERY_STUB_ENABLED` / `SMS_DELIVERY_STUB_ENABLED` — no FCM/APNs/Twilio yet. |

---

## Partial — needs extension or polish

| ID / area | Spec reference | Current state | Gap |
|-----------|----------------|---------------|-----|
| **Pause queue** | FR-09, UC-13 | `Provider.is_paused` blocks **remote** joins; walk-ins still allowed when open. Updated via `ProviderUpdate`. | First-class pause/resume endpoints + exact spec copy (banner, join button parity) may differ; **per-service-line pause** vs whole business needs product decision. |
| **Smart pre-alerts** | FR-07 | Position-based alerts in `notifications/domain/triggers.py` (`you_are_next`, `head_to_counter`). | No **travel time** / ETA; no GPS-based “start heading” sophistication from doc. |
| **Broadcasts** | FR-08, UC-11 | Create/list, idempotency, severity, realtime fan-out. | Optional: preset templates, stricter “waiting-only” dispatch rules per exact PDF wording. |
| ~~**Notification inbox UX**~~ | ~~Product~~ | ~~`notification` ledger + list endpoint.~~ | **Done:** `read_at` + `POST /me/notifications/{id}/read`. |
| **EWT proof** | FR-06, NFR-01 | WMA in `queue/application/ewt.py` + discovery. | No bundled **simulation dataset** or performance proof for report/demo. |
---

## Spec mismatches — code exists but violates or diverges from doc

| Issue | Spec / intent | Where | Fix direction |
|-------|----------------|-------|---------------|
| ~~**No-show from wrong state**~~ | ~~US-SP-06: no-show **after** called~~ | ~~`queue/domain/ticket_rules.py`~~ | **Done (2026):** `no_show` requires `serving`, same as `completed`. |
| **Call-next auto-completes serving** | Some QMS specs: call next only promotes waiting→serving; complete is separate | `queue/application/service.py` — `call_next_transition` marks current `serving` as `completed` before taking next. | Product decision: keep (fast kiosk) vs split into explicit “complete current” + “call next”. |
| **Review eligibility** | FR-11 wording: after provider marks completed | `reviews/domain/review_rules.py` checks `ticket_status == completed` only. | Usually sufficient; optional: assert last transition actor if you need literal “provider closed ticket”. |
---

## Non-functional (backend-relevant)

| ID | Requirement | Note |
|----|--------------|------|
| **NFR-01** | &lt;2s sync via WebSockets | Architecture supports it; no SLO tests or monitoring in repo. |
| **NFR-03** | 1k concurrent joins | Not load-tested in codebase. |
| **NFR-04** | Encryption at rest | App does not implement field-level encryption; depends on Postgres/hosting. |
| **NFR-05** | 99.5% uptime | Operational; not enforced in code. |
---

## Suggested implementation order (backend only)

1. ~~**Spec correctness:** Tighten `no_show` transition rules~~ **Done.** Optionally revisit call-next semantics.
2. ~~**FR-10:** DELETE service with active-ticket check~~ **Done.**
3. ~~**FR-09:** Recall endpoint + tests~~ **Done.**
4. ~~**FR-04:** Join body with lat/lng + Haversine vs `join_radius_m`~~ **Done.**
5. ~~**FR-05:** Liveness model + top-K workflow + tests~~ **Done (MVP:** ping + flagged hint; no moving-vector / “converging” heuristic).**
6. ~~**FR-02 / UC-12:** QR source + deep-link join resolution.~~ **Done.**
7. ~~**NFR-02:** Offline batch sync API + idempotency store.~~ **Done.**
8. ~~**UC-07:** Event emission hooks + analytics queries + CSV export.~~ **Done (MVP).**
9. ~~**UC-10:** Documents table + upload + reject reason.~~ **Done (MVP).**
10. ~~**UC-15 / UC-16:** Health/metrics and governance APIs as needed.~~ **Done (MVP).**
---

## Reference files (starting points)

| Topic | Files |
|-------|-------|
| Remote join / walk-in / recall / liveness / invites / batch | `backend/werefa/queue/application/service.py`, `…/liveness_service.py`, `…/join_invite_service.py`, `…/kiosk_batch_service.py`, `backend/werefa/queue/interface/router.py` |
| Join resolve (public) | `backend/werefa/join_invites/interface/router.py` |
| Demand analytics | `backend/werefa/analytics/application/service.py`, `…/interface/router.py` |
| Admin health / users | `backend/werefa/admin/interface/router.py`, `…/application/service.py` |
| Ticket rules | `backend/werefa/queue/domain/ticket_rules.py` |
| Services CRUD + delete | `backend/werefa/service_items/interface/router.py`, `…/application/service.py` |
| Provider + discover | `backend/werefa/providers/application/service.py`, `…/interface/router.py`, `…/documents_service.py` |
| Strikes | `backend/werefa/strikes/` |
| Reviews | `backend/werefa/reviews/` |
| Notifications | `backend/werefa/notifications/` |
| Auth + OTP | `backend/werefa/identity/application/service.py`, `…/otp_service.py` |
| Broadcasts | `backend/werefa/broadcasts/` |
| Realtime | `backend/werefa/realtime/` |

---

**Last reviewed:** aligned with backend audit vs `docs/doc.md` (Chapter 3 FR/NFR and UC tables). Update this file when items ship.
