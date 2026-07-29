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
    """Queue-entry liveness for remote top-K presence (FR-05)."""

    idle = "idle"
    awaiting = "awaiting"
    ok = "ok"
    flagged = "flagged"


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


class DemandEventType(str, Enum):
    """High-level funnel / queue analytics (UC-07, lost demand)."""

    join_remote = "join_remote"
    join_walk_in = "join_walk_in"
    join_qr = "join_qr"
    join_walk_in_batch = "join_walk_in_batch"
    service_view = "service_view"
    queue_abandon = "queue_abandon"
    queue_cleared = "queue_cleared"
