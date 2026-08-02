from enum import Enum


class UserType(str, Enum):
    """Account intent: customers use queues; providers run businesses; admin is platform staff."""

    customer = "customer"
    provider = "provider"
    admin = "admin"


class VerificationStatus(str, Enum):
    pending = "pending"
    verified = "verified"
    rejected = "rejected"


class ProviderDocumentKind(str, Enum):
    trade_license = "trade_license"
    owner_id = "owner_id"
    address_proof = "address_proof"
    health_permit = "health_permit"
    establishment_letter = "establishment_letter"
    tin_certificate = "tin_certificate"
    other = "other"


class MembershipRole(str, Enum):
    owner = "owner"
    staff = "staff"


class TicketStatus(str, Enum):
    waiting = "waiting"
    serving = "serving"
    completed = "completed"
    no_show = "no_show"
    cancelled = "cancelled"
    pending_approval = "pending_approval"


class ApprovalQueueOrder(str, Enum):
    """How approved remote joins are ordered in the FIFO line."""

    preserve_register_time = "preserve_register_time"
    approval_time = "approval_time"


class JoinDocumentKind(str, Enum):
    """Plain-language file types seekers may upload when joining."""

    image = "image"
    pdf = "pdf"
    any = "any"


class TicketSource(str, Enum):
    remote_app = "remote_app"
    kiosk_walk_in = "kiosk_walk_in"
    qr_scan = "qr_scan"


class LivenessState(str, Enum):
    """Queue-entry liveness for remote top-K presence (FR-05).

    ``ok`` means "the customer deliberately confirmed, recently" — it does
    *not* claim we know where they are. A check-in from a device with no
    location fix sets ``ok`` too; whether a fix came with it is recorded
    in ``last_ping_at``. Tying ``ok`` to GPS alone was the single biggest
    source of false flags.

    Only a check-in reaches ``ok``. Background polling from the app is
    recorded in ``last_seen_at`` and leaves the state where it is, so a
    silent absentee still reaches ``flagged``.
    """

    idle = "idle"
    awaiting = "awaiting"
    ok = "ok"
    flagged = "flagged"


class LivenessAction(str, Enum):
    """What staff should *do* about a top-K ticket right now (FR-05).

    The state tells you what we observed; the action tells you what to do
    about it. Keeping them separate is deliberate — ``flagged`` on its own
    never says whether to wait, call, or hold, which is why it was easy to
    read as "this person is a no-show" when it usually is not.
    """

    # Nothing to decide: not a remote ticket, not waiting, or outside top-K.
    none = "none"
    # No concerns — call them in the normal order.
    proceed = "proceed"
    # They confirmed, but we have no recent location fix. Call them; a
    # failed GPS read is not evidence of absence.
    verify = "verify"
    # They never confirmed through the grace windows — hold their spot and
    # serve the next customer instead of burning the slot.
    hold = "hold"


class BroadcastSeverity(str, Enum):
    """Provider broadcast severity tags (FR-08).

    The split keeps the wire format stable while letting clients decorate
    each message visually (e.g. info banner, warning toast, critical
    interstitial)."""

    info = "info"
    warning = "warning"
    critical = "critical"


class NotificationKind(str, Enum):
    """Reasons the system reaches out to a customer (FR-07)."""

    head_to_counter = "head_to_counter"
    you_are_next = "you_are_next"
    # FR-05 / Phase 11: prompt for GPS ping when entering top-K remotely.
    liveness_ping_request = "liveness_ping_request"
    # Customer was promoted to serving (staff pressed Call next).
    now_serving = "now_serving"
    # Top-K liveness deadline passed without a fresh location ping.
    liveness_stale = "liveness_stale"
    # Staff parked the ticket after repeated silence: the spot is kept, the
    # line moves on. Deliberately worded as a reprieve, not a penalty.
    liveness_hold = "liveness_hold"
    # Provider/staff posted in line chat.
    line_chat_update = "line_chat_update"
    # Staff cleared the line for the day; ticket closed, joins paused.
    queue_cleared = "queue_cleared"


class NotificationChannel(str, Enum):
    """Delivery transports for outbound notifications.

    The order in a user's ``notification_prefs`` decides which channel
    is tried first; ``logger`` is the always-deliverable backstop so
    every dispatch produces at least one ledger row.
    """

    websocket = "websocket"
    email = "email"
    push = "push"
    sms = "sms"
    logger = "logger"


class NotificationStatus(str, Enum):
    delivered = "delivered"
    failed = "failed"
    skipped = "skipped"
    queued = "queued"
    """Handed to the delivery worker; the outcome is not known yet.

    Only ever set for channels that leave the machine (SMS, email). A row
    that is still ``queued`` long after ``created_at`` means the worker
    lost the job — a process restart is the expected cause.
    """

    sent = "sent"
    """The gateway accepted the message; the handset has not confirmed it.

    Only ever set for a channel that issues *delivery receipts* and was
    asked for one — in practice SMS with a status callback configured.
    ``delivered`` used to be written the moment Twilio returned a 201,
    which is an acceptance, not an arrival: a wrong number, a barred
    handset or a carrier that silently drops the message all look
    identical to a real delivery from that side of the call.

    The row moves on when the receipt lands — ``delivered`` or ``failed``
    — see ``werefa.notifications.domain.receipts``. A row left at ``sent``
    means no receipt ever came, which is an honest "we do not know"
    rather than the false ``delivered`` it replaced. Nothing sweeps those:
    unlike ``queued`` there is no job to resume, and re-sending a message
    the gateway accepted risks texting somebody twice.
    """


class NotificationReach(str, Enum):
    """Did an alert actually get in front of the customer?

    Read off a ledger row rather than assumed, because the two questions
    the ledger answers are not the same one: ``status`` says what the
    delivery machinery managed, ``channel`` says who (if anyone) it
    managed it *to*. A row reading ``delivered`` on the ``logger`` channel
    is a complete success by the dispatcher's standards and told the
    customer nothing at all — ``logger`` is the always-succeeds backstop
    ``_user_prefs`` appends so every dispatch leaves a trace.

    This exists because FR-05 liveness draws conclusions from silence. A
    customer who never received the "tap to confirm" prompt has not
    ignored us, and flagging them for it turns our delivery failure into
    their problem — see :mod:`werefa.queue.domain.liveness_rules`.
    """

    confirmed = "confirmed"
    """It reached them: a channel that talks to the customer reported a
    delivery, and (for SMS) the carrier receipt agreed."""

    unconfirmed = "unconfirmed"
    """We cannot tell. Still queued, or accepted by a gateway that never
    sent a receipt. Treated as the old behaviour — the benefit of the
    doubt is only extended against *proof*, never against ignorance."""

    not_reached = "not_reached"
    """Provably nobody was told: every customer-facing channel failed, or
    the only thing that "delivered" was the logger backstop."""


class DemandEventType(str, Enum):
    """High-level funnel / queue analytics (UC-07, lost demand)."""

    join_remote = "join_remote"
    join_walk_in = "join_walk_in"
    join_qr = "join_qr"
    join_walk_in_batch = "join_walk_in_batch"
    service_view = "service_view"
    queue_abandon = "queue_abandon"
    queue_cleared = "queue_cleared"
