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


class BroadcastSeverity(str, Enum):
    """Provider broadcast severity tags (FR-08).

    The split keeps the wire format stable while letting clients decorate
    each message visually (e.g. info banner, warning toast, critical
    interstitial)."""

    info = "info"
    warning = "warning"
    critical = "critical"
