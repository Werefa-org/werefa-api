"""Startup reconciliation of notifications the worker never finished (FR-07).

Two halves, mirroring where the code lives.

* **Policy** — :func:`decide_reconcile`, pure arithmetic over an age and a
  kind. This is where "would we really re-text somebody twenty minutes
  late?" gets answered, so it is asserted directly rather than inferred
  from a sweep's side effects.
* **The sweep** — the pass over the ledger. Run against the *real*
  database on purpose: the whole failure mode being fixed is a row that
  sits in Postgres reading ``queued``, and ``notification.status`` carries
  a ``CHECK`` constraint that fake sessions cannot enforce.

The delivery queue is swapped for a recorder throughout. A reconciled
retry is asserted as "this exact job went back on the worker" — whether
the worker then delivers it is ``test_deferred_dispatch``'s business, and
re-testing it here would only couple these assertions to the gateway
doubles.
"""

from __future__ import annotations

import uuid
from collections.abc import Generator
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from tests.utils.user import create_random_user
from tests.utils.utils import random_lower_string
from werefa.core.config import settings
from werefa.core.db import engine
from werefa.main import app
from werefa.notifications.application import reconcile as reconcile_module
from werefa.notifications.application import service as notifications_service
from werefa.notifications.application.reconcile import (
    reconcile_stuck_notifications,
)
from werefa.notifications.domain.reconcile import (
    DURABLE_KINDS,
    ZombieAction,
    decide_reconcile,
)
from werefa.notifications.infrastructure.delivery import DeliveryJob
from werefa.notifications.notifier import DeliveryOutcome, NotificationPayload
from werefa.shared.enums import (
    NotificationChannel,
    NotificationKind,
    NotificationStatus,
    TicketSource,
)
from werefa.shared.models import (
    Notification,
    Provider,
    QueueEntry,
    ServiceItem,
    User,
    utcnow,
)

MIN_AGE = 300.0
MAX_AGE = 3600.0

# One of each, so a rule change on either side breaks a named test rather
# than a parametrised blur.
DURABLE = NotificationKind.queue_cleared
POSITIONAL = NotificationKind.you_are_next


# --- policy: pure rules ---------------------------------------------------


def _decide(
    kind: NotificationKind | None,
    age: float | None,
    *,
    attempts: int = 0,
) -> ZombieAction:
    return decide_reconcile(
        kind=kind,
        age_seconds=age,
        delivery_attempts=attempts,
        min_age_seconds=MIN_AGE,
        max_age_seconds=MAX_AGE,
    )


def test_a_young_row_is_left_alone() -> None:
    """It is probably in flight this second. Another process — a replica,
    or the old half of a rolling deploy — may be mid-send on it, and
    stealing that job is how you double-text somebody."""
    assert _decide(DURABLE, MIN_AGE - 1) is ZombieAction.leave
    assert _decide(POSITIONAL, MIN_AGE - 1) is ZombieAction.leave


def test_the_floor_is_inclusive() -> None:
    assert _decide(DURABLE, MIN_AGE) is ZombieAction.retry


def test_a_durable_alert_past_the_floor_is_retried() -> None:
    assert _decide(DURABLE, MIN_AGE + 60) is ZombieAction.retry


def test_a_position_alert_is_failed_rather_than_sent_late() -> None:
    """"You're next" five minutes late is not a partial win — it walks
    somebody to a counter that served them long ago. Same reasoning that
    expires parked jobs in the delivery queue."""
    assert _decide(POSITIONAL, MIN_AGE + 60) is ZombieAction.fail


def test_every_position_critical_kind_is_treated_that_way() -> None:
    """Guards the opt-in list: a kind nobody classified must not drift
    into late re-sends."""
    for kind in NotificationKind:
        expected = (
            ZombieAction.retry if kind in DURABLE_KINDS else ZombieAction.fail
        )
        assert _decide(kind, MIN_AGE + 60) is expected, kind


def test_even_a_durable_alert_expires_eventually() -> None:
    assert _decide(DURABLE, MAX_AGE + 1) is ZombieAction.fail


def test_an_unmeasurable_age_is_never_retried() -> None:
    """No ``created_at`` means no way to prove the message is still worth
    sending, and unknown is not a licence to text somebody."""
    assert _decide(DURABLE, None) is ZombieAction.fail


def test_an_unrecognised_kind_is_never_retried() -> None:
    """A row written by a newer image, read after a rollback."""
    assert _decide(None, MIN_AGE + 60) is ZombieAction.fail


def test_a_ceiling_below_the_floor_disables_retries() -> None:
    """The documented way to run reconciliation in resolve-only mode."""
    action = decide_reconcile(
        kind=DURABLE,
        age_seconds=MIN_AGE + 60,
        delivery_attempts=0,
        min_age_seconds=MIN_AGE,
        max_age_seconds=1.0,
    )
    assert action is ZombieAction.fail


def test_a_send_that_already_reached_a_gateway_is_never_repeated() -> None:
    """The crash that motivates the counter: the gateway accepted, the
    process died before the ledger heard about it. Re-sending would put a
    second text on somebody's phone; ``failed`` merely understates a
    delivery we cannot confirm."""
    assert _decide(DURABLE, MIN_AGE + 60, attempts=1) is ZombieAction.fail


def test_freshness_does_not_override_a_possible_delivery() -> None:
    """No amount of "the message is still worth sending" makes a duplicate
    acceptable, so the attempt check comes first."""
    assert _decide(DURABLE, MIN_AGE, attempts=1) is ZombieAction.fail
    assert _decide(DURABLE, MIN_AGE) is ZombieAction.retry


def test_an_attempted_row_is_still_left_alone_while_young() -> None:
    """Below the floor the attempt may yet resolve itself — the worker
    that made it could be one line away from writing ``delivered``."""
    assert _decide(DURABLE, MIN_AGE - 1, attempts=1) is ZombieAction.leave


# --- the sweep: against a real ledger -------------------------------------


@dataclass
class _CaptureQueue:
    """Stands in for the delivery worker. Records, never sends."""

    jobs: list[DeliveryJob] = field(default_factory=list)

    def start(self) -> None:
        return None

    def stop(self, *, timeout: float = 5.0) -> None:
        return None

    def submit(self, job: DeliveryJob) -> bool:
        self.jobs.append(job)
        return True

    def defer(self, job: DeliveryJob) -> bool:
        return True


@dataclass
class _Harness:
    db: Session
    user: User
    queue: _CaptureQueue

    def ticket(self) -> QueueEntry:
        """A real ticket on a real service line.

        Built through the models rather than the API: the sweep only reads
        ``service_item_id`` off it, and a join flow would drag in geofence,
        approval and strike rules that have nothing to do with this.
        """
        provider = Provider(
            slug=random_lower_string(), biz_name="Reconcile Clinic"
        )
        self.db.add(provider)
        self.db.commit()
        item = ServiceItem(
            provider_id=provider.id,
            name="Consultation",
            avg_duration_minutes=10,
            price=Decimal("0.00"),
        )
        self.db.add(item)
        self.db.commit()
        entry = QueueEntry(
            service_item_id=item.id,
            user_id=self.user.id,
            ticket_number=1,
            source=TicketSource.remote_app.value,
        )
        self.db.add(entry)
        self.db.commit()
        self.db.refresh(entry)
        return entry

    def stuck_row(
        self,
        *,
        age_seconds: float,
        kind: NotificationKind = DURABLE,
        channel: NotificationChannel = NotificationChannel.sms,
        status: NotificationStatus = NotificationStatus.queued,
        user: User | None = None,
        ticket: QueueEntry | None = None,
        delivery_attempts: int = 0,
    ) -> Notification:
        row = Notification(
            user_id=(user or self.user).id,
            ticket_id=None if ticket is None else ticket.id,
            kind=kind.value,
            body="the line has closed for today",
            channel=channel.value,
            status=status.value,
            delivery_attempts=delivery_attempts,
            created_at=utcnow() - timedelta(seconds=age_seconds),
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def sweep(self) -> reconcile_module.ReconcileReport:
        return reconcile_stuck_notifications(session=self.db)

    def status_of(self, row: Notification) -> str:
        self.db.expire_all()
        fresh = self.db.exec(
            select(Notification).where(Notification.id == row.id)
        ).one()
        return fresh.status


@pytest.fixture
def harness(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> Generator[_Harness, None, None]:
    # ``settings`` is process-global, so every override goes through
    # monkeypatch — a leaked threshold here would change how *other*
    # modules' tests resolve alerts.
    monkeypatch.setattr(settings, "NOTIFICATION_DELIVERY_ASYNC", True)
    monkeypatch.setattr(
        settings, "NOTIFICATION_RECONCILE_MIN_AGE_SECONDS", MIN_AGE
    )
    monkeypatch.setattr(
        settings, "NOTIFICATION_RECONCILE_MAX_AGE_SECONDS", MAX_AGE
    )
    monkeypatch.setattr(settings, "NOTIFICATION_RECONCILE_MAX_ROWS", 500)

    queue = _CaptureQueue()
    notifications_service.set_delivery_queue(queue)  # type: ignore[arg-type]
    user = create_random_user(db)
    try:
        yield _Harness(db=db, user=user, queue=queue)
    finally:
        notifications_service.set_delivery_queue(None)


def test_a_stuck_row_is_handed_back_to_the_worker(harness: _Harness) -> None:
    """The whole point: a crash mid-send left this row ``queued`` and
    nothing ever went back for it."""
    row = harness.stuck_row(age_seconds=MIN_AGE + 60)

    report = harness.sweep()

    assert report.requeued == 1
    assert report.failed == 0
    assert [j.notification_id for j in harness.queue.jobs] == [row.id]
    # Still ``queued`` — the worker owns the transition, exactly as it does
    # for a freshly dispatched row.
    assert harness.status_of(row) == NotificationStatus.queued.value


def test_the_requeued_job_carries_the_rows_own_details(
    harness: _Harness,
) -> None:
    row = harness.stuck_row(age_seconds=MIN_AGE + 60)

    harness.sweep()

    job = harness.queue.jobs[0]
    assert job.channel is NotificationChannel.sms
    assert job.payload.kind is DURABLE
    assert job.payload.body == row.body
    assert job.user_id == harness.user.id
    # Not marked ``upgrade_only``: nothing has settled this row, so a
    # failure on the retry must be recorded as one.
    assert job.upgrade_only is False
    assert job.attempt == 0


def test_the_alert_keeps_the_time_it_was_raised(harness: _Harness) -> None:
    """A reconciled send is a late delivery of an old alert, not a new
    one — dating it "now" would misrepresent when the line closed."""
    row = harness.stuck_row(age_seconds=MIN_AGE + 60)

    harness.sweep()

    assert harness.queue.jobs[0].payload.occurred_at == row.created_at


def test_a_stale_position_alert_is_marked_failed_and_never_sent(
    harness: _Harness,
) -> None:
    row = harness.stuck_row(age_seconds=MIN_AGE + 60, kind=POSITIONAL)

    report = harness.sweep()

    assert harness.queue.jobs == []
    assert report.failed == 1
    assert harness.status_of(row) == NotificationStatus.failed.value


def test_a_row_still_within_the_floor_is_untouched(harness: _Harness) -> None:
    """A live worker may be on it right now."""
    row = harness.stuck_row(age_seconds=MIN_AGE - 60)

    report = harness.sweep()

    assert report.scanned == 0
    assert harness.queue.jobs == []
    assert harness.status_of(row) == NotificationStatus.queued.value


def test_settled_rows_are_not_reopened(harness: _Harness) -> None:
    """Only ``queued`` is ambiguous. A ``delivered`` row is a send that
    happened, and re-sending it would double-text."""
    delivered = harness.stuck_row(
        age_seconds=MIN_AGE + 60, status=NotificationStatus.delivered
    )
    failed = harness.stuck_row(
        age_seconds=MIN_AGE + 60, status=NotificationStatus.failed
    )

    report = harness.sweep()

    assert report.scanned == 0
    assert harness.queue.jobs == []
    assert harness.status_of(delivered) == NotificationStatus.delivered.value
    assert harness.status_of(failed) == NotificationStatus.failed.value


def test_a_row_that_already_reached_a_gateway_is_not_re_sent(
    harness: _Harness,
) -> None:
    """The crash this guards: the gateway accepted the text, the process
    died before the ledger caught up. The row is closed out, not re-sent."""
    row = harness.stuck_row(age_seconds=MIN_AGE + 60, delivery_attempts=1)

    report = harness.sweep()

    assert harness.queue.jobs == []
    assert report.failed == 1
    assert report.unconfirmed == 1
    assert harness.status_of(row) == NotificationStatus.failed.value


def test_the_unconfirmed_count_separates_the_two_kinds_of_failure(
    harness: _Harness,
) -> None:
    """"We know this never went out" and "we cannot tell" both land on
    ``failed``, but only one of them means the process is dying mid-send."""
    harness.stuck_row(age_seconds=MIN_AGE + 60, kind=POSITIONAL)
    harness.stuck_row(age_seconds=MIN_AGE + 60, delivery_attempts=2)

    report = harness.sweep()

    assert report.failed == 2
    assert report.unconfirmed == 1


def test_a_row_past_the_ceiling_is_failed_rather_than_sent(
    harness: _Harness,
) -> None:
    row = harness.stuck_row(age_seconds=MAX_AGE + 60)

    report = harness.sweep()

    assert harness.queue.jobs == []
    assert report.failed == 1
    assert harness.status_of(row) == NotificationStatus.failed.value


def test_a_row_with_no_created_at_is_failed(harness: _Harness) -> None:
    """Rows predating the timestamped column still have to be resolved —
    an unmeasurable age is what the ``IS NULL`` arm of the query is for."""
    row = harness.stuck_row(age_seconds=MIN_AGE + 60)
    row.created_at = None
    harness.db.add(row)
    harness.db.commit()

    report = harness.sweep()

    assert report.scanned == 1
    assert harness.queue.jobs == []
    assert harness.status_of(row) == NotificationStatus.failed.value


def test_a_deactivated_recipient_is_resolved_not_texted(
    harness: _Harness,
) -> None:
    """Same rule the worker applies before every send."""
    other = create_random_user(harness.db)
    row = harness.stuck_row(age_seconds=MIN_AGE + 60, user=other)
    other.is_active = False
    harness.db.add(other)
    harness.db.commit()

    report = harness.sweep()

    assert harness.queue.jobs == []
    assert report.failed == 1
    assert harness.status_of(row) == NotificationStatus.failed.value


def test_a_channel_that_never_queues_is_resolved_not_retried(
    harness: _Harness,
) -> None:
    """``queued`` is only ever written for a channel that leaves the box,
    so a local one here is corrupt data — resolve it, do not resume it."""
    row = harness.stuck_row(
        age_seconds=MIN_AGE + 60, channel=NotificationChannel.websocket
    )

    report = harness.sweep()

    assert harness.queue.jobs == []
    assert report.failed == 1
    assert harness.status_of(row) == NotificationStatus.failed.value


def test_the_rollback_lever_resolves_without_re_queueing(
    harness: _Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``NOTIFICATION_DELIVERY_ASYNC=false`` means "no off-request sends".
    Zombies still need an ending, but not by starting the very work the
    lever exists to stop."""
    monkeypatch.setattr(settings, "NOTIFICATION_DELIVERY_ASYNC", False)
    row = harness.stuck_row(age_seconds=MIN_AGE + 60)

    report = harness.sweep()

    assert harness.queue.jobs == []
    assert report.failed == 1
    assert harness.status_of(row) == NotificationStatus.failed.value


def test_the_fall_through_list_is_rebuilt_from_the_users_prefs(
    harness: _Harness,
) -> None:
    """The job dispatch handed over carried the untried preferences; a
    reconciled one has to carry them too, or a permanently dead gateway
    stops falling through to anything."""
    harness.user.notification_prefs = ["sms", "push", "logger"]
    harness.db.add(harness.user)
    harness.db.commit()
    harness.stuck_row(age_seconds=MIN_AGE + 60)

    harness.sweep()

    assert harness.queue.jobs[0].fallback_channels == (
        NotificationChannel.push,
        NotificationChannel.logger,
    )


def test_a_channel_the_user_has_since_dropped_falls_through_to_nothing(
    harness: _Harness,
) -> None:
    """Their current prefs are the only list we have. Falling through to
    channels *after* a preference they deleted would be inventing one."""
    harness.user.notification_prefs = ["websocket", "logger"]
    harness.db.add(harness.user)
    harness.db.commit()
    harness.stuck_row(age_seconds=MIN_AGE + 60)

    harness.sweep()

    assert harness.queue.jobs[0].fallback_channels == ()


def test_email_stays_out_of_the_fall_through_when_it_is_a_copy(
    harness: _Harness,
) -> None:
    """Queue-critical kinds send email as a separate copy with no ledger
    row, so dispatch skips it in the fall-through — a reconciled job that
    put it back would deliver the copy twice."""
    harness.user.notification_prefs = ["sms", "email", "logger"]
    harness.db.add(harness.user)
    harness.db.commit()
    harness.stuck_row(age_seconds=MIN_AGE + 60, kind=DURABLE)

    harness.sweep()

    assert NotificationKind.queue_cleared in notifications_service.EMAIL_COPY_KINDS
    assert harness.queue.jobs[0].fallback_channels == (
        NotificationChannel.logger,
    )


def test_a_sweep_is_capped_and_says_so(
    harness: _Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A long outage strands thousands of rows, and boot is the worst
    moment to walk all of them."""
    monkeypatch.setattr(settings, "NOTIFICATION_RECONCILE_MAX_ROWS", 2)
    for _ in range(3):
        harness.stuck_row(age_seconds=MIN_AGE + 60)

    report = harness.sweep()

    assert report.scanned == 2
    assert report.truncated is True


def test_a_clean_ledger_is_a_no_op(harness: _Harness) -> None:
    report = harness.sweep()

    assert report == reconcile_module.ReconcileReport()


def test_reconciliation_opens_its_own_session_when_given_none() -> None:
    """Startup has no request session to borrow — the sweep has to be able
    to reach the database on its own."""
    queue = _CaptureQueue()
    notifications_service.set_delivery_queue(queue)  # type: ignore[arg-type]
    try:
        report = reconcile_stuck_notifications()
    finally:
        notifications_service.set_delivery_queue(None)

    assert isinstance(report, reconcile_module.ReconcileReport)


def test_the_service_line_is_recovered_from_the_ticket(
    harness: _Harness,
) -> None:
    """``service_item_id`` is the one thing a job needs that the ledger
    never stored, so it is re-read from the ticket. Without it a
    fall-through to the websocket channel silently delivers nothing."""
    ticket = harness.ticket()
    row = harness.stuck_row(age_seconds=MIN_AGE + 60, ticket=ticket)

    harness.sweep()

    job = harness.queue.jobs[0]
    assert job.notification_id == row.id
    assert job.payload.ticket_id == ticket.id
    assert job.payload.service_item_id == ticket.service_item_id


def test_a_ticket_that_went_away_does_not_stop_the_retry(
    harness: _Harness,
) -> None:
    """Tickets vanish (``ondelete=SET NULL`` on the ledger), and losing the
    deep link is no reason to withhold the message itself."""
    harness.stuck_row(age_seconds=MIN_AGE + 60)

    harness.sweep()

    assert harness.queue.jobs[0].payload.service_item_id is None


def test_rows_are_swept_oldest_first(harness: _Harness) -> None:
    """The cap makes order matter: whatever is deferred to the next
    restart should be the freshest, not the most abandoned."""
    oldest = harness.stuck_row(age_seconds=MIN_AGE + 600)
    middle = harness.stuck_row(age_seconds=MIN_AGE + 300)
    newest = harness.stuck_row(age_seconds=MIN_AGE + 60)

    harness.sweep()

    assert [j.notification_id for j in harness.queue.jobs] == [
        oldest.id,
        middle.id,
        newest.id,
    ]


def test_another_users_stuck_row_is_swept_too(harness: _Harness) -> None:
    """Nothing about reconciliation is scoped to one recipient — it is a
    property of the process that died, not of a customer."""
    other = create_random_user(harness.db)
    mine = harness.stuck_row(age_seconds=MIN_AGE + 60)
    theirs = harness.stuck_row(age_seconds=MIN_AGE + 120, user=other)

    report = harness.sweep()

    assert report.requeued == 2
    assert {j.notification_id for j in harness.queue.jobs} == {
        mine.id,
        theirs.id,
    }
    assert {j.user_id for j in harness.queue.jobs} == {
        harness.user.id,
        other.id,
    }


# --- the two guarantees reconciliation rests on --------------------------
#
# Both live in the worker, but they exist for this module's benefit, so
# they are asserted here — and against the real database, because the
# claim is specifically about what is *committed* at a given instant. A
# fake session cannot tell "written" from "written and durable", which is
# the entire distinction being relied on.


@dataclass
class _RemoteSpy:
    """A gateway that reports what the ledger looked like when it was
    called — read through a session of its own, so a value it sees really
    is committed and would survive the process being killed here."""

    outcome: DeliveryOutcome
    notification_id: uuid.UUID
    attempts_seen: list[int] = field(default_factory=list)
    channel: NotificationChannel = NotificationChannel.sms
    ready: bool = True

    def deliver(self, *, user: object, payload: object) -> DeliveryOutcome:
        with Session(engine) as fresh:
            row = fresh.get(Notification, self.notification_id)
            self.attempts_seen.append(row.delivery_attempts if row else -1)
        return self.outcome

    def send(self, *, user: object, payload: object) -> bool:
        return self.deliver(user=user, payload=payload) is DeliveryOutcome.delivered


def _run_worker_on(harness: _Harness, row: Notification, spy: _RemoteSpy) -> None:
    notifications_service.set_registry({NotificationChannel.sms: spy})  # type: ignore[dict-item]
    try:
        notifications_service.deliver_job(
            DeliveryJob(
                user_id=harness.user.id,
                channel=NotificationChannel.sms,
                payload=NotificationPayload(kind=DURABLE, body=row.body),
                notification_id=row.id,
                last_attempt=True,
            )
        )
    finally:
        notifications_service.set_registry(None)
    harness.db.expire_all()


def test_the_attempt_is_committed_before_the_gateway_is_called(
    harness: _Harness,
) -> None:
    """The ordering is the whole mechanism. If the counter were written
    after the provider answered, a process killed mid-send would leave
    ``0`` behind and reconciliation would text the customer again."""
    row = harness.stuck_row(age_seconds=MIN_AGE + 60)
    spy = _RemoteSpy(DeliveryOutcome.delivered, row.id)

    _run_worker_on(harness, row, spy)

    assert spy.attempts_seen == [1]


def test_a_worker_that_dies_mid_send_leaves_a_trace_reconcile_honours(
    harness: _Harness,
) -> None:
    """End to end on the exact failure the user hit: the gateway takes the
    message, the process dies before resolving the row, the next boot must
    not send it again."""
    row = harness.stuck_row(age_seconds=MIN_AGE + 60)
    # The gateway accepts, and then nothing — no resolution, as if the
    # process were killed the instant after this returns.
    spy = _RemoteSpy(DeliveryOutcome.delivered, row.id)
    notifications_service.set_registry({NotificationChannel.sms: spy})  # type: ignore[dict-item]
    try:
        notifications_service._mark_attempt(harness.db, row.id)
        spy.deliver(user=None, payload=None)
    finally:
        notifications_service.set_registry(None)
    harness.db.expire_all()
    assert harness.status_of(row) == NotificationStatus.queued.value

    report = harness.sweep()

    assert harness.queue.jobs == []
    assert report.unconfirmed == 1
    assert harness.status_of(row) == NotificationStatus.failed.value


def test_a_late_job_cannot_overwrite_a_settled_row(harness: _Harness) -> None:
    """The other half: reconciliation hands the job out again, and *then*
    the original worker finishes. The row it settled is the truth, and the
    latecomer's ``failed`` must not land on top of it."""
    row = harness.stuck_row(
        age_seconds=MIN_AGE + 60, status=NotificationStatus.delivered
    )
    spy = _RemoteSpy(DeliveryOutcome.permanent, row.id)

    _run_worker_on(harness, row, spy)

    assert harness.status_of(row) == NotificationStatus.delivered.value


def test_a_late_success_cannot_overwrite_a_settled_row_either(
    harness: _Harness,
) -> None:
    """Even a *successful* duplicate must leave the row alone — rewriting
    it would hide that two sends went out."""
    row = harness.stuck_row(
        age_seconds=MIN_AGE + 60,
        channel=NotificationChannel.email,
        status=NotificationStatus.failed,
    )
    spy = _RemoteSpy(DeliveryOutcome.delivered, row.id)

    _run_worker_on(harness, row, spy)

    assert harness.status_of(row) == NotificationStatus.failed.value


def test_the_shed_upgrade_is_still_allowed_through(harness: _Harness) -> None:
    """The one documented write onto a settled row. Overload sheds to a
    local channel and settles the row there; the parked remote send that
    lands afterwards is meant to promote it to the channel the user
    actually ranked first."""
    row = harness.stuck_row(
        age_seconds=MIN_AGE + 60,
        channel=NotificationChannel.logger,
        status=NotificationStatus.delivered,
    )
    spy = _RemoteSpy(DeliveryOutcome.delivered, row.id)

    notifications_service.set_registry({NotificationChannel.sms: spy})  # type: ignore[dict-item]
    try:
        notifications_service.deliver_job(
            DeliveryJob(
                user_id=harness.user.id,
                channel=NotificationChannel.sms,
                payload=NotificationPayload(kind=DURABLE, body=row.body),
                notification_id=row.id,
                upgrade_only=True,
                last_attempt=True,
            )
        )
    finally:
        notifications_service.set_registry(None)
    harness.db.expire_all()

    fresh = harness.db.get(Notification, row.id)
    assert fresh is not None
    assert fresh.channel == NotificationChannel.sms.value
    assert fresh.status == NotificationStatus.delivered.value


# --- startup wiring ------------------------------------------------------


def test_booting_the_app_resolves_what_the_last_process_left_behind(
    harness: _Harness,
) -> None:
    """The end-to-end shape of the fix: a process died holding this send,
    and the *next* one to boot is what closes it out. Asserted through a
    real lifespan because the wiring — after the queue starts, before any
    traffic — is the part that makes it a restart-recovery."""
    stale = harness.stuck_row(age_seconds=MIN_AGE + 60, kind=POSITIONAL)
    still_worth_sending = harness.stuck_row(age_seconds=MIN_AGE + 60)

    with TestClient(app):
        pass

    assert harness.status_of(stale) == NotificationStatus.failed.value
    assert [j.notification_id for j in harness.queue.jobs] == [
        still_worth_sending.id
    ]


def test_startup_reconciliation_can_be_turned_off(
    harness: _Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "NOTIFICATION_RECONCILE_ON_STARTUP", False)
    row = harness.stuck_row(age_seconds=MIN_AGE + 60, kind=POSITIONAL)

    with TestClient(app):
        pass

    assert harness.status_of(row) == NotificationStatus.queued.value
    assert harness.queue.jobs == []


def test_a_failing_sweep_does_not_stop_the_app_booting(
    harness: _Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A database that is slow or unhappy at boot is a reason to log, not
    a reason to refuse to serve — the rows are still there next restart."""

    def _explode(**_kwargs: object) -> None:
        raise RuntimeError("database is having a moment")

    monkeypatch.setattr(
        "werefa.notifications.application.reconcile."
        "reconcile_stuck_notifications",
        _explode,
    )
    row = harness.stuck_row(age_seconds=MIN_AGE + 60, kind=POSITIONAL)

    with TestClient(app) as client:
        assert client.get(f"{settings.API_V1_STR}/utils/health-check/").is_success

    assert harness.status_of(row) == NotificationStatus.queued.value


def test_a_recipient_that_cannot_be_loaded_yields_no_job(
    harness: _Harness,
) -> None:
    """Belt and braces. The foreign key means the sweep should never meet
    this row, so it is asserted against the guard directly rather than by
    forging a state the database refuses to hold."""
    orphan = Notification(
        user_id=uuid.uuid4(),
        kind=DURABLE.value,
        body="the line has closed for today",
        channel=NotificationChannel.sms.value,
        status=NotificationStatus.queued.value,
    )

    job = reconcile_module._job_for(
        harness.db, orphan, kind=DURABLE, channel=NotificationChannel.sms
    )

    assert job is None
