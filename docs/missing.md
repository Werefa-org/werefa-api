# Werefa backend — missing & partial scope

This document tracks **backend** gaps versus `docs/doc.md` (FR/UC/NFR) and internal product expectations. Use it as the implementation backlog.

**Status legend:** Missing | Partial | Spec mismatch (code exists but behavior does not match the PDF)

---

## Critical missing (no or negligible backend support)

| ID / area | Spec reference | What’s missing |
|-----------|----------------|----------------|
| ~~**Join-time geofence**~~ | ~~FR-04, UC-02, UC-14~~ | **Done:** Remote join accepts optional `latitude` / `longitude` on `QueueJoin`. When `Provider.join_radius_m` is set, coordinates are required and distance (Haversine via `provider_repo.distance_meters`) must be ≤ radius; walk-ins unchanged. |
| **Liveness / presence** | FR-05, UC-03 | Top-of-queue GPS checks, position pings, `liveness_state`, flagged-vs-no-show rules. No data model or endpoints. |
| **QR / deep link entry** | FR-02, UC-12 | `TicketSource` only has `remote_app` and `kiosk_walk_in`. Need `qr_scan` (or equivalent), resolve deep link / token to provider+service, optional join bypass rules per spec. |
| **Offline kiosk sync** | NFR-02, Scenario D | Batch walk-in ingest with idempotency, conflict resolution, replay-safe API. |
| ~~**Recall customer**~~ | ~~FR-09~~ | **Done:** `POST /service-items/{id}/recall` — staff-only; most recent **completed** ticket on the line within `RECALL_COMPLETED_WINDOW_SECONDS` (default 90s) returns to **serving**; 409 if someone is already serving, if a review exists, or if the customer already has another active ticket. |
| ~~**Delete service**~~ | ~~FR-10, UC-09~~ | **Done:** `DELETE /providers/{pid}/services/{sid}` — 204 when no `waiting`/`serving` tickets; 409 otherwise; staff-only. |
| **Demand analytics** | UC-07 | No event log (`demand_event` or similar), no aggregates, no CSV export. |
| **Lost demand / abandonment** | Scenario C, UC-07 | No tracking of view→abandon, paused-while-attempting, etc. |
| **Admin system health API** | UC-15 | Only lightweight `GET /api/v1/utils/health-check/`. No WS client counts, error feed, resource metrics for an-admin dashboard. |
| **Admin user governance** | UC-16, Scenario E | No full ban/suspend with audit, search-by-phone, forced reset PIN flow as described in doc. (Partial: strikes admin unblock exists.) |
| **KYC documents** | UC-10 | No `provider_document` storage, upload, download. Verify/reject only flip `verification_status`. |
| **Reject reason persistence** | UC-10 acceptance | `POST …/admin/providers/{id}/reject` has no body; spec wants reason/comment on reject. |
| **OTP / lockout / auth depth** | US-SYS-00 | Email/password JWT only — no lockout table, no OTP endpoints. |
| **Real push / SMS** | Narratives FR-07, UC-05 | Notifier abstraction exists; no FCM/APNs/Twilio-class integration. |

---

## Partial — needs extension or polish

| ID / area | Spec reference | Current state | Gap |
|-----------|----------------|---------------|-----|
| **Pause queue** | FR-09, UC-13 | `Provider.is_paused` blocks **remote** joins; walk-ins still allowed when open. Updated via `ProviderUpdate`. | First-class pause/resume endpoints + exact spec copy (banner, join button parity) may differ; **per-service-line pause** vs whole business needs product decision. |
| **Smart pre-alerts** | FR-07 | Position-based alerts in `notifications/domain/triggers.py` (`you_are_next`, `head_to_counter`). | No **travel time** / ETA; no GPS-based “start heading” sophistication from doc. |
| **Broadcasts** | FR-08, UC-11 | Create/list, idempotency, severity, realtime fan-out. | Optional: preset templates, stricter “waiting-only” dispatch rules per exact PDF wording. |
| **Notification inbox UX** | Product | `notification` ledger + list endpoint. | No **`read` / `read_at`** (or equivalent) for unread counts in UI. |
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
5. **FR-05:** Liveness model + top-K workflow + tests.
6. **FR-02 / UC-12:** QR source + deep-link join resolution.
7. **NFR-02:** Offline batch sync API + idempotency store.
8. **UC-07:** Event emission hooks + analytics queries + CSV export.
9. **UC-10:** Documents table + upload + reject reason.
10. **UC-15 / UC-16:** Health/metrics and governance APIs as needed.

---

## Reference files (starting points)

| Topic | Files |
|-------|--------|
| Remote join / walk-in + recall | `backend/werefa/queue/application/service.py`, `backend/werefa/queue/interface/router.py` |
| Ticket rules | `backend/werefa/queue/domain/ticket_rules.py` |
| Services CRUD + delete | `backend/werefa/service_items/interface/router.py`, `…/application/service.py` |
| Provider + discover | `backend/werefa/providers/application/service.py`, `…/interface/router.py` |
| Strikes | `backend/werefa/strikes/` |
| Reviews | `backend/werefa/reviews/` |
| Notifications | `backend/werefa/notifications/` |
| Broadcasts | `backend/werefa/broadcasts/` |
| Realtime | `backend/werefa/realtime/` |
| Auth | `backend/werefa/identity/` |

---

**Last reviewed:** aligned with backend audit vs `docs/doc.md` (Chapter 3 FR/NFR and UC tables). Update this file when items ship.
