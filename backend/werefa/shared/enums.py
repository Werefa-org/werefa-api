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


class MembershipRole(str, Enum):
    owner = "owner"
    staff = "staff"


class TicketStatus(str, Enum):
    waiting = "waiting"
    serving = "serving"
    completed = "completed"
    no_show = "no_show"
    cancelled = "cancelled"


class TicketSource(str, Enum):
    remote_app = "remote_app"
    kiosk_walk_in = "kiosk_walk_in"


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


class NotificationChannel(str, Enum):
    """Delivery transports for outbound notifications.

    The order in a user's ``notification_prefs`` decides which channel
    is tried first; ``logger`` is the always-deliverable backstop so
    every dispatch produces at least one ledger row.
    """

    websocket = "websocket"
    email = "email"
    logger = "logger"


class NotificationStatus(str, Enum):
    delivered = "delivered"
    failed = "failed"
    skipped = "skipped"
