from enum import Enum


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
