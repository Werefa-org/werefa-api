import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Literal

from pydantic import EmailStr, model_validator
from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    Index,
    Numeric,
    UniqueConstraint,
    text,
)
from sqlmodel import Field, Relationship, SQLModel
from typing_extensions import Self

from werefa.shared.enums import (
    ApprovalQueueOrder,
    BroadcastSeverity,
    JoinDocumentKind,
    LivenessState,
    MembershipRole,
    TicketStatus,
    UserType,
    VerificationStatus,
)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# --- User (auth + profile) ---


class UserBase(SQLModel):
    email: EmailStr = Field(unique=True, index=True, max_length=255)
    is_active: bool = True
    is_superuser: bool = False
    full_name: str | None = Field(default=None, max_length=255)
    phone_number: str | None = Field(default=None, max_length=20)
    user_type: str = Field(default=UserType.customer.value, max_length=32)


class UserCreate(UserBase):
    password: str = Field(min_length=8, max_length=128)

    @model_validator(mode="after")
    def sync_user_type_with_superuser(self) -> Self:
        if self.is_superuser:
            self.user_type = UserType.admin.value
        elif self.user_type == UserType.admin.value:
            raise ValueError("admin user_type is only allowed for superuser accounts")
        return self


class UserRegister(SQLModel):
    email: EmailStr = Field(max_length=255)
    password: str = Field(min_length=8, max_length=128)
    full_name: str | None = Field(default=None, max_length=255)
    user_type: Literal["customer", "provider"] = Field(default="customer")


class UserUpdate(UserBase):
    email: EmailStr | None = Field(default=None, max_length=255)  # type: ignore[assignment]
    password: str | None = Field(default=None, min_length=8, max_length=128)


class UserUpdateMe(SQLModel):
    """Self-edit payload for ``PATCH /users/me``.

    Deliberately *does not* include ``user_type`` — role upgrades go
    through the dedicated ``POST /users/me/become-provider`` endpoint
    so identity changes don't ride along with profile edits (HIGH-4).
    """

    full_name: str | None = Field(default=None, max_length=255)
    email: EmailStr | None = Field(default=None, max_length=255)
    phone_number: str | None = Field(default=None, max_length=20)


class UpdatePassword(SQLModel):
    current_password: str = Field(min_length=8, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


class User(UserBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    hashed_password: str
    created_at: datetime | None = Field(
        default_factory=utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    # Set when a strike accrual pushes the user past STRIKE_LIMIT, or by an
    # admin override. ``None`` means "no active block"; a past timestamp is
    # equivalent to no block (the active check uses ``> utcnow()``).
    joins_blocked_until: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    # Ordered list of preferred notification channels (FR-07). New users
    # start at ``settings.NOTIFICATION_DEFAULT_PREFS``; the migration
    # backfills NULLs to the same default. JSON keeps the list ordering
    # without an extra join table.
    notification_prefs: list[str] | None = Field(
        default=None,
        sa_column=Column(JSON, nullable=True),
    )
    provider_memberships: list["ProviderMembership"] = Relationship(
        back_populates="user", cascade_delete=True
    )
    queue_entries: list["QueueEntry"] = Relationship(
        back_populates="user",
        cascade_delete=False,
        sa_relationship_kwargs={
            "primaryjoin": "QueueEntry.user_id == User.id",
            "foreign_keys": "QueueEntry.user_id",
        },
    )
    strikes: list["UserStrike"] = Relationship(
        back_populates="user", cascade_delete=True
    )
    notifications: list["Notification"] = Relationship(
        back_populates="user", cascade_delete=True
    )
    is_suspended: bool = Field(default=False)
    suspended_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    suspended_reason: str | None = Field(default=None, max_length=500)
    failed_login_count: int = Field(default=0, ge=0)
    locked_until: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    profile_image_public_id: str | None = Field(default=None, max_length=500)
    profile_image_resource_type: str | None = Field(default=None, max_length=16)


class UserPublic(UserBase):
    id: uuid.UUID
    created_at: datetime | None = None
    joins_blocked_until: datetime | None = None
    notification_prefs: list[str] | None = None
    profile_image_url: str | None = None


class UsersPublic(SQLModel):
    data: list[UserPublic]
    count: int


# --- Provider ---


class ProviderBase(SQLModel):
    slug: str = Field(max_length=64, unique=True, index=True)
    biz_name: str = Field(max_length=200)
    verification_status: str = Field(
        default=VerificationStatus.pending.value, max_length=32
    )
    is_open: bool = True
    is_paused: bool = False
    join_radius_m: int | None = Field(default=None, ge=1)
    latitude: float | None = None
    longitude: float | None = None
    is_private: bool = False
    # Extended business profile
    category: str | None = Field(default=None, max_length=64)
    description: str | None = Field(default=None, max_length=1000)
    region: str | None = Field(default=None, max_length=100)
    city: str | None = Field(default=None, max_length=100)
    address: str | None = Field(default=None, max_length=500)
    phone: str | None = Field(default=None, max_length=20)
    show_phone_public: bool = False
    website: str | None = Field(default=None, max_length=200)
    biz_email: str | None = Field(default=None, max_length=255)


class ProviderCreate(ProviderBase):
    owner_user_id: uuid.UUID | None = None
    access_code: str | None = Field(default=None, max_length=6)


class ProviderUpdate(SQLModel):
    biz_name: str | None = Field(default=None, max_length=200)
    is_open: bool | None = None
    is_paused: bool | None = None
    join_radius_m: int | None = Field(default=None, ge=1)
    latitude: float | None = None
    longitude: float | None = None
    is_private: bool | None = None
    access_code: str | None = Field(default=None, max_length=6)
    category: str | None = Field(default=None, max_length=64)
    description: str | None = Field(default=None, max_length=1000)
    region: str | None = Field(default=None, max_length=100)
    city: str | None = Field(default=None, max_length=100)
    address: str | None = Field(default=None, max_length=500)
    phone: str | None = Field(default=None, max_length=20)
    show_phone_public: bool | None = None
    website: str | None = Field(default=None, max_length=200)
    biz_email: str | None = Field(default=None, max_length=255)


class Provider(ProviderBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    # Stored alongside the rest of the provider row but intentionally
    # *not* re-exported on ``ProviderPublic``. Owners rotate it via
    # ``ProviderUpdate``; readers must request it through the staff-only
    # endpoint introduced in this pass.
    access_code: str | None = Field(default=None, max_length=6)
    created_at: datetime | None = Field(
        default_factory=utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    # Aggregated rating counters; kept on the provider row so discovery
    # and detail reads stay O(1). Updated transactionally with each new review.
    ratings_count: int = Field(default=0, ge=0)
    ratings_sum: int = Field(default=0, ge=0)
    estimate_accurate_count: int = Field(default=0, ge=0)
    memberships: list["ProviderMembership"] = Relationship(
        back_populates="provider", cascade_delete=True
    )
    service_items: list["ServiceItem"] = Relationship(
        back_populates="provider", cascade_delete=True
    )
    reviews: list["Review"] = Relationship(
        back_populates="provider", cascade_delete=True
    )
    last_rejection_reason: str | None = Field(default=None, max_length=1000)
    profile_image_public_id: str | None = Field(default=None, max_length=500)
    profile_image_resource_type: str | None = Field(default=None, max_length=16)


class ProviderPublic(ProviderBase):
    id: uuid.UUID
    created_at: datetime | None = None
    ratings_count: int = 0
    rating_avg: float | None = None
    profile_image_url: str | None = None


class ProviderStaffPublic(ProviderPublic):
    """Staff/owner view: includes the rotating access code so staff can
    share it. Returned by ``GET /providers/{id}/access-code``."""

    access_code: str | None = None
    last_rejection_reason: str | None = None


class MyProviderPublic(ProviderPublic):
    """Row shape for ``GET /users/me/providers``.

    Extends ``ProviderPublic`` with the caller's role on that provider so
    the dashboard can badge "Owner" vs "Staff" without a second query.
    """

    membership_role: str
    last_rejection_reason: str | None = None


class MyProvidersPublic(SQLModel):
    data: list[MyProviderPublic]
    count: int


class ProviderDiscoveryPublic(ProviderPublic):
    distance_m: int | None = None
    active_tickets: int = 0
    serving_tickets: int = 0
    estimated_wait_minutes: int | None = None
    load_factor: str | None = Field(default=None, max_length=16)


class ProviderDiscoveriesPublic(SQLModel):
    data: list[ProviderDiscoveryPublic]
    count: int


class DiscoveryCitiesPublic(SQLModel):
    data: list[str]
    count: int


class DiscoveryRegionsPublic(SQLModel):
    data: list[str]
    count: int


# --- Membership ---


class ProviderMembership(SQLModel, table=True):
    __tablename__ = "provider_membership"
    __table_args__ = (
        UniqueConstraint("provider_id", "user_id", name="uq_membership_provider_user"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    provider_id: uuid.UUID = Field(foreign_key="provider.id", ondelete="CASCADE")
    user_id: uuid.UUID = Field(foreign_key="user.id", ondelete="CASCADE")
    role: str = Field(default=MembershipRole.staff.value, max_length=32)

    provider: Provider | None = Relationship(back_populates="memberships")
    user: User | None = Relationship(back_populates="provider_memberships")


class MembershipCreate(SQLModel):
    user_id: uuid.UUID
    role: MembershipRole = MembershipRole.staff


class MembershipPublic(SQLModel):
    id: uuid.UUID
    provider_id: uuid.UUID
    user_id: uuid.UUID
    role: str


class ProviderMemberPublic(SQLModel):
    membership: MembershipPublic
    user: UserPublic


# --- Service item (one FIFO line per row) ---


class ServiceItemBase(SQLModel):
    name: str = Field(min_length=1, max_length=120)
    avg_duration_minutes: int = Field(ge=1, le=24 * 60)
    price: Decimal = Field(sa_column=Column(Numeric(10, 2), nullable=False))
    is_active: bool = True
    description: str | None = Field(default=None, max_length=1000)
    requirements: str | None = Field(default=None, max_length=500)
    category: str | None = Field(default=None, max_length=64)
    is_paused: bool = False
    is_private: bool = False
    allow_vip: bool = False
    vip_code: str | None = Field(default=None, max_length=20)
    line_chat_enabled: bool = True
    requires_join_approval: bool = False
    approval_queue_order: str = Field(
        default=ApprovalQueueOrder.preserve_register_time.value,
        max_length=32,
    )
    requires_join_documents: bool = False
    join_document_requirements: list[dict] | None = Field(
        default=None,
        sa_column=Column(JSON, nullable=True),
    )


class JoinDocumentRequirement(SQLModel):
    """One document slot seekers must fill when joining (stored on service line)."""

    label: str = Field(min_length=1, max_length=120)
    kind: str = Field(
        default=JoinDocumentKind.any.value,
        max_length=16,
    )


class ServiceItemCreate(ServiceItemBase):
    pass


class ServiceItemUpdate(SQLModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    avg_duration_minutes: int | None = Field(default=None, ge=1, le=24 * 60)
    price: Decimal | None = None
    is_active: bool | None = None
    description: str | None = Field(default=None, max_length=1000)
    requirements: str | None = Field(default=None, max_length=500)
    category: str | None = Field(default=None, max_length=64)
    is_paused: bool | None = None
    is_private: bool | None = None
    allow_vip: bool | None = None
    vip_code: str | None = Field(default=None, max_length=20)
    line_chat_enabled: bool | None = None
    requires_join_approval: bool | None = None
    approval_queue_order: str | None = Field(default=None, max_length=32)
    requires_join_documents: bool | None = None
    join_document_requirements: list[dict] | None = None


class ServiceItem(ServiceItemBase, table=True):
    __tablename__ = "service_item"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    provider_id: uuid.UUID = Field(foreign_key="provider.id", ondelete="CASCADE")
    next_ticket_number: int = Field(default=1, ge=1)
    line_chat_cleared_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )

    provider: Provider | None = Relationship(back_populates="service_items")
    queue_entries: list["QueueEntry"] = Relationship(
        back_populates="service_item", cascade_delete=True
    )


class ServiceItemPublic(ServiceItemBase):
    id: uuid.UUID
    provider_id: uuid.UUID


# --- Queue entry (ticket) ---


class QueueEntryBase(SQLModel):
    ticket_number: int = Field(ge=1)
    status: str = Field(default=TicketStatus.waiting.value, max_length=32)
    source: str = Field(max_length=32)
    guest_name: str | None = Field(default=None, max_length=100)
    guest_phone: str | None = Field(default=None, max_length=32)
    guest_email: str | None = Field(default=None, max_length=255)
    priority: int = Field(default=0, ge=0, le=10)


class QueueEntry(QueueEntryBase, table=True):
    __tablename__ = "queue_entry"
    __table_args__ = (
        Index(
            "ix_queue_entry_one_active_user",
            "user_id",
            unique=True,
            postgresql_where=text(
                "user_id IS NOT NULL AND (status)::text IN "
                "('waiting','serving','pending_approval')"
            ),
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    service_item_id: uuid.UUID = Field(
        foreign_key="service_item.id", ondelete="CASCADE"
    )
    user_id: uuid.UUID | None = Field(
        default=None,
        foreign_key="user.id",
        ondelete="SET NULL",
    )
    joined_at: datetime | None = Field(
        default_factory=utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    # Stamped when a ticket transitions ``waiting → serving`` so the EWT
    # service-line WMA can compute real serve duration as
    # ``completed_at - serving_started_at`` (Phase 8).
    serving_started_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    completed_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    # Tracks the last position at which we sent a smart pre-alert (FR-07).
    # Used to suppress duplicates: an alert is only emitted when the
    # ticket reaches a trigger position *and* this column doesn't already
    # match. ``None`` means no alerts have been sent for this ticket.
    last_alert_position: int | None = Field(default=None, ge=1)

    # FR-05: top-of-queue presence; see ``position_ping`` + liveness sync.
    liveness_state: str = Field(
        default=LivenessState.idle.value,
        max_length=16,
    )
    liveness_deadline_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    # Set when staff clears the line (e.g. end of day). Ticket rows stay for analytics.
    close_reason: str | None = Field(default=None, max_length=32)
    approved_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    approved_by_user_id: uuid.UUID | None = Field(
        default=None,
        foreign_key="user.id",
        ondelete="SET NULL",
    )

    service_item: ServiceItem | None = Relationship(back_populates="queue_entries")
    user: User | None = Relationship(
        back_populates="queue_entries",
        sa_relationship_kwargs={
            "primaryjoin": "QueueEntry.user_id == User.id",
            "foreign_keys": "QueueEntry.user_id",
        },
    )
    approved_by: User | None = Relationship(
        sa_relationship_kwargs={
            "primaryjoin": "QueueEntry.approved_by_user_id == User.id",
            "foreign_keys": "QueueEntry.approved_by_user_id",
        },
    )
    position_pings: list["PositionPing"] = Relationship(
        back_populates="ticket",
        cascade_delete=True,
    )
    join_documents: list["TicketJoinDocument"] = Relationship(
        back_populates="ticket",
        cascade_delete=True,
    )


class TicketJoinDocument(SQLModel, table=True):
    """File uploaded by a seeker when joining a queue line."""

    __tablename__ = "ticket_join_document"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    ticket_id: uuid.UUID = Field(
        foreign_key="queue_entry.id",
        ondelete="CASCADE",
        index=True,
    )
    slot_index: int = Field(ge=0, le=20)
    label: str = Field(max_length=120)
    kind: str = Field(max_length=16)
    filename: str = Field(max_length=255)
    content_type: str = Field(max_length=120)
    storage_relpath: str = Field(max_length=500)
    resource_type: str = Field(default="raw", max_length=16)
    created_at: datetime | None = Field(
        default_factory=utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )

    ticket: QueueEntry | None = Relationship(back_populates="join_documents")


class TicketJoinDocumentPublic(SQLModel):
    id: uuid.UUID
    ticket_id: uuid.UUID
    slot_index: int
    label: str
    kind: str
    filename: str
    content_type: str
    created_at: datetime | None = None
    download_url: str


class TicketJoinDocumentsPublic(SQLModel):
    data: list[TicketJoinDocumentPublic]
    count: int


class ProviderCustomerBlock(SQLModel, table=True):
    """Provider-scoped ban — blocked users cannot join this business remotely."""

    __tablename__ = "provider_customer_block"
    __table_args__ = (
        UniqueConstraint("provider_id", "user_id", name="uq_provider_customer_block"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    provider_id: uuid.UUID = Field(foreign_key="provider.id", ondelete="CASCADE")
    user_id: uuid.UUID = Field(foreign_key="user.id", ondelete="CASCADE")
    blocked_by_user_id: uuid.UUID | None = Field(
        default=None,
        foreign_key="user.id",
        ondelete="SET NULL",
    )
    reason: str | None = Field(default=None, max_length=500)
    created_at: datetime | None = Field(
        default_factory=utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )


class PositionPing(SQLModel, table=True):
    __tablename__ = "position_ping"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    ticket_id: uuid.UUID = Field(
        foreign_key="queue_entry.id",
        ondelete="CASCADE",
        index=True,
    )
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    accuracy_m: int | None = Field(default=None, ge=0)
    sent_at: datetime | None = Field(
        default_factory=utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )

    ticket: QueueEntry | None = Relationship(back_populates="position_pings")


class QueueJoin(SQLModel):
    access_code: str | None = Field(default=None, max_length=6)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    invite_token: str | None = Field(
        default=None,
        max_length=64,
        description="FR-02: optional QR/deep-link token for this service line.",
    )
    vip_code: str | None = Field(default=None, max_length=20)

    @model_validator(mode="after")
    def _coords_paired(self) -> Self:
        if (self.latitude is None) ^ (self.longitude is None):
            raise ValueError("latitude and longitude must be supplied together")
        return self


class WalkInCreate(SQLModel):
    guest_name: str | None = Field(default=None, max_length=100)
    guest_phone: str | None = Field(default=None, max_length=32)
    guest_email: str | None = Field(default=None, max_length=255)
    is_vip: bool = False


class TicketStatusUpdate(SQLModel):
    status: TicketStatus


class TicketPriorityUpdate(SQLModel):
    priority: int = Field(ge=0, le=10)


class WalkInBatchItem(SQLModel):
    client_ref: str | None = Field(default=None, max_length=120)
    guest_name: str | None = Field(default=None, max_length=100)
    guest_phone: str | None = Field(default=None, max_length=32)
    guest_email: str | None = Field(default=None, max_length=255)


class JoinInviteCreate(SQLModel):
    ttl_hours: int = Field(default=24, ge=1, le=24 * 14)


class JoinInviteCreated(SQLModel):
    token: str
    expires_at: datetime


class JoinInviteResolved(SQLModel):
    service_item_id: uuid.UUID
    provider_id: uuid.UUID
    slug: str
    biz_name: str


class QueueEntryPublic(QueueEntryBase):
    id: uuid.UUID
    service_item_id: uuid.UUID
    provider_id: uuid.UUID | None = None
    user_id: uuid.UUID | None = None
    joined_at: datetime | None = None
    completed_at: datetime | None = None
    liveness_state: str = Field(default=LivenessState.idle.value, max_length=16)
    liveness_deadline_at: datetime | None = None
    close_reason: str | None = None
    approved_at: datetime | None = None
    user_full_name: str | None = None
    user_email: str | None = None
    user_phone: str | None = None
    is_banned: bool = False


class ProviderCustomerPublic(SQLModel):
    user_id: uuid.UUID
    full_name: str | None = None
    email: str | None = None
    phone_number: str | None = None
    is_banned: bool = False
    ticket_count: int = 0
    last_joined_at: datetime | None = None
    has_active_ticket: bool = False


class ProviderCustomersPublic(SQLModel):
    data: list[ProviderCustomerPublic]
    count: int


class ProviderBanCreate(SQLModel):
    user_id: uuid.UUID
    reason: str | None = Field(default=None, max_length=500)


class TicketApprovalBody(SQLModel):
    queue_order: ApprovalQueueOrder | None = Field(
        default=None,
        description="Override service default for this approval only.",
    )


class ClearQueueResult(SQLModel):
    cleared_count: int = 0
    notified_count: int = 0
    is_paused: bool = True


class QueueAheadPreview(SQLModel):
    ticket_number: int = Field(ge=1)
    position: int = Field(ge=1)
    is_vip: bool = False
    is_you: bool = False


class TicketQueueSnapshot(SQLModel):
    service_item_id: uuid.UUID
    service_name: str
    provider_id: uuid.UUID
    biz_name: str
    profile_image_url: str | None = None
    avg_duration_minutes: int = Field(ge=1)
    waiting_count: int = Field(ge=0)
    serving_count: int = Field(ge=0)
    vip_waiting_count: int = Field(ge=0)
    your_ticket_id: uuid.UUID
    your_ticket_number: int = Field(ge=1)
    your_position: int | None = Field(default=None, ge=1)
    people_ahead: int = Field(ge=0)
    estimated_wait_minutes: int | None = None
    pace_note: str = Field(max_length=200)
    ahead_preview: list[QueueAheadPreview] = Field(default_factory=list)


class ServiceLinePreview(SQLModel):
    """Public queue stats before joining (no ticket required)."""

    service_item_id: uuid.UUID
    service_name: str
    provider_id: uuid.UUID
    biz_name: str
    profile_image_url: str | None = None
    avg_duration_minutes: int = Field(ge=1)
    waiting_count: int = Field(ge=0)
    serving_count: int = Field(ge=0)
    vip_waiting_count: int = Field(ge=0)
    estimated_wait_minutes: int | None = None
    pace_note: str = Field(max_length=200)
    is_accepting_remote_joins: bool = True


class KioskSyncBatchIn(SQLModel):
    idempotency_key: str = Field(min_length=8, max_length=120)
    walk_ins: list[WalkInBatchItem] = Field(min_length=1, max_length=200)


class KioskSyncBatchOut(SQLModel):
    """Replay-safe response for offline kiosk sync (NFR-02)."""

    idempotent_replay: bool
    tickets: list[QueueEntryPublic]


class PositionPingCreate(SQLModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    accuracy_m: int | None = Field(default=None, ge=0)


class LivenessPublic(SQLModel):
    ticket_id: uuid.UUID
    liveness_state: str
    liveness_deadline_at: datetime | None = None
    last_ping_at: datetime | None = None
    last_latitude: float | None = None
    last_longitude: float | None = None
    last_accuracy_m: int | None = None


class QueueEntriesPublic(SQLModel):
    data: list[QueueEntryPublic]
    count: int


# --- Review ---


class ReviewBase(SQLModel):
    rating: int = Field(ge=1, le=5)
    was_estimate_accurate: bool
    comment: str | None = Field(default=None, max_length=1000)


class ReviewCreate(ReviewBase):
    pass


class Review(ReviewBase, table=True):
    __tablename__ = "review"
    __table_args__ = (
        UniqueConstraint("ticket_id", name="uq_review_ticket"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    ticket_id: uuid.UUID = Field(
        foreign_key="queue_entry.id", ondelete="CASCADE", index=True
    )
    user_id: uuid.UUID = Field(foreign_key="user.id", ondelete="CASCADE", index=True)
    provider_id: uuid.UUID = Field(
        foreign_key="provider.id", ondelete="CASCADE", index=True
    )
    service_item_id: uuid.UUID = Field(
        foreign_key="service_item.id", ondelete="CASCADE", index=True
    )
    created_at: datetime | None = Field(
        default_factory=utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )

    provider: Provider | None = Relationship(back_populates="reviews")


class ReviewPublic(ReviewBase):
    id: uuid.UUID
    ticket_id: uuid.UUID
    provider_id: uuid.UUID
    service_item_id: uuid.UUID
    created_at: datetime | None = None


class ReviewsPublic(SQLModel):
    data: list[ReviewPublic]
    count: int


class ProviderRatingSummary(SQLModel):
    provider_id: uuid.UUID
    ratings_count: int = 0
    rating_avg: float | None = None
    estimate_accuracy_rate: float | None = None


# --- Strike (FR-12) ---


class UserStrike(SQLModel, table=True):
    """One row per recorded penalty. Read-mostly; never mutated.

    Today the only ``kind`` is ``"no_show"``, but the column is left open so
    other penalty kinds (e.g. ``"abuse"``) can be added without a migration.
    """

    __tablename__ = "user_strike"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID = Field(
        foreign_key="user.id", ondelete="CASCADE", index=True
    )
    ticket_id: uuid.UUID = Field(
        foreign_key="queue_entry.id", ondelete="CASCADE", index=True
    )
    provider_id: uuid.UUID = Field(
        foreign_key="provider.id", ondelete="CASCADE", index=True
    )
    kind: str = Field(default="no_show", max_length=32)
    created_at: datetime | None = Field(
        default_factory=utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )

    user: User | None = Relationship(back_populates="strikes")


class UserStrikePublic(SQLModel):
    id: uuid.UUID
    ticket_id: uuid.UUID
    provider_id: uuid.UUID
    kind: str
    created_at: datetime | None = None


class UserStrikesPublic(SQLModel):
    data: list[UserStrikePublic]
    count: int
    joins_blocked_until: datetime | None = None
    window_days: int
    limit: int


# --- Provider broadcast (FR-08) ---


class BroadcastMessageBase(SQLModel):
    body: str = Field(min_length=1, max_length=500)
    severity: str = Field(
        default=BroadcastSeverity.info.value, max_length=16
    )


class BroadcastCreate(BroadcastMessageBase):
    """Body of ``POST /providers/{provider_id}/broadcasts``.

    ``service_item_id``: when omitted, the broadcast targets *every* active
    service line of the provider; otherwise just the specified one.

    ``idempotency_key``: optional client-supplied de-dupe key. The unique
    index on the column means a retried request with the same key returns
    the originally created record without re-publishing the realtime event.
    """

    service_item_id: uuid.UUID | None = None
    idempotency_key: str | None = Field(default=None, max_length=80)


class BroadcastMessage(BroadcastMessageBase, table=True):
    __tablename__ = "broadcast_message"
    __table_args__ = (
        UniqueConstraint(
            "provider_id",
            "idempotency_key",
            name="uq_broadcast_provider_idem_key",
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    provider_id: uuid.UUID = Field(
        foreign_key="provider.id", ondelete="CASCADE", index=True
    )
    service_item_id: uuid.UUID | None = Field(
        default=None,
        foreign_key="service_item.id",
        ondelete="CASCADE",
        index=True,
    )
    author_user_id: uuid.UUID = Field(
        foreign_key="user.id", ondelete="CASCADE", index=True
    )
    idempotency_key: str | None = Field(default=None, max_length=80)
    created_at: datetime | None = Field(
        default_factory=utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )


class BroadcastPublic(BroadcastMessageBase):
    id: uuid.UUID
    provider_id: uuid.UUID
    service_item_id: uuid.UUID | None = None
    author_user_id: uuid.UUID
    author_role: str = Field(default=MembershipRole.staff.value, max_length=32)
    author_label: str = Field(default="Business", max_length=200)
    created_at: datetime | None = None


class BroadcastsPublic(SQLModel):
    data: list[BroadcastPublic]
    count: int


# --- Line chat (per service queue) ---


class LineChatMessageBase(SQLModel):
    body: str = Field(min_length=1, max_length=500)


class LineChatCreate(LineChatMessageBase):
    pass


class LineChatMessage(LineChatMessageBase, table=True):
    __tablename__ = "line_chat_message"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    service_item_id: uuid.UUID = Field(
        foreign_key="service_item.id", ondelete="CASCADE", index=True
    )
    author_user_id: uuid.UUID = Field(
        foreign_key="user.id", ondelete="CASCADE", index=True
    )
    created_at: datetime | None = Field(
        default_factory=utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )


class LineChatMessagePublic(LineChatMessageBase):
    id: uuid.UUID
    service_item_id: uuid.UUID
    author_user_id: uuid.UUID
    author_role: str = Field(default="seeker", max_length=32)
    author_label: str = Field(default="Guest", max_length=200)
    created_at: datetime | None = None


class LineChatMessagesPublic(SQLModel):
    data: list[LineChatMessagePublic]
    count: int
    line_chat_enabled: bool = True


# --- Notifications (FR-07) ---


class NotificationBase(SQLModel):
    kind: str = Field(max_length=32)
    body: str = Field(min_length=1, max_length=500)
    channel: str = Field(max_length=16)
    status: str = Field(max_length=16)


class Notification(NotificationBase, table=True):
    """Append-only ledger of every alert dispatched (FR-07).

    One row per (user, ticket, position trigger) is emitted regardless of
    delivery success. ``status`` records what happened on the chosen
    channel; ``channel`` reflects the *first deliverable* preference at
    dispatch time (or ``logger`` if everything else failed, since
    ``LoggerNotifier`` always succeeds).
    """

    __tablename__ = "notification"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID = Field(
        foreign_key="user.id", ondelete="CASCADE", index=True
    )
    ticket_id: uuid.UUID | None = Field(
        default=None,
        foreign_key="queue_entry.id",
        ondelete="SET NULL",
        index=True,
    )
    position: int | None = Field(default=None, ge=1)
    created_at: datetime | None = Field(
        default_factory=utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    read_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )

    user: User | None = Relationship(back_populates="notifications")


class NotificationPublic(NotificationBase):
    id: uuid.UUID
    ticket_id: uuid.UUID | None = None
    position: int | None = None
    created_at: datetime | None = None
    read_at: datetime | None = None


class NotificationsPublic(SQLModel):
    data: list[NotificationPublic]
    count: int
    unread_count: int = 0


class NotificationUnreadCount(SQLModel):
    unread_count: int


class NotificationPrefsUpdate(SQLModel):
    """Body of ``PATCH /users/me/notifications``."""

    notification_prefs: list[str] = Field(
        description=(
            "Ordered list of channel keys (e.g. "
            "[\"websocket\",\"email\",\"push\",\"sms\"]); the first deliverable channel "
            "wins per dispatch. Channels not recognised by the server "
            "are rejected with 400."
        ),
        min_length=1,
        max_length=8,
    )


# --- Join invites (FR-02) ---


class JoinInvite(SQLModel, table=True):
    __tablename__ = "join_invite"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    token: str = Field(unique=True, index=True, max_length=64)
    service_item_id: uuid.UUID = Field(
        foreign_key="service_item.id",
        ondelete="CASCADE",
    )
    created_at: datetime | None = Field(
        default_factory=utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    expires_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
    revoked_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )


# --- Offline kiosk batches (NFR-02) ---


class KioskSyncBatch(SQLModel, table=True):
    __tablename__ = "kiosk_sync_batch"
    __table_args__ = (
        UniqueConstraint(
            "service_item_id",
            "idempotency_key",
            name="uq_kiosk_sync_batch_service_idem",
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    service_item_id: uuid.UUID = Field(
        foreign_key="service_item.id",
        ondelete="CASCADE",
    )
    idempotency_key: str = Field(max_length=120)
    created_at: datetime | None = Field(
        default_factory=utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    result_json: dict = Field(sa_column=Column(JSON, nullable=False))


# --- Demand / analytics (UC-07) ---


class DemandEvent(SQLModel, table=True):
    __tablename__ = "demand_event"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    event_type: str = Field(max_length=48, index=True)
    provider_id: uuid.UUID | None = Field(
        default=None,
        foreign_key="provider.id",
        ondelete="SET NULL",
    )
    service_item_id: uuid.UUID | None = Field(
        default=None,
        foreign_key="service_item.id",
        ondelete="SET NULL",
    )
    user_id: uuid.UUID | None = Field(
        default=None,
        foreign_key="user.id",
        ondelete="SET NULL",
    )
    client_ref: str | None = Field(default=None, max_length=120)
    payload: dict | None = Field(default=None, sa_column=Column(JSON, nullable=True))
    created_at: datetime | None = Field(
        default_factory=utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )


class DemandEventIngest(SQLModel):
    event_type: str = Field(max_length=48)
    provider_id: uuid.UUID | None = None
    service_item_id: uuid.UUID | None = None
    client_ref: str | None = Field(default=None, max_length=120)
    payload: dict | None = None


class ProviderAnalyticsSummary(SQLModel):
    page_views: int = 0
    joins: int = 0
    completions: int = 0
    cancellations: int = 0
    no_shows: int = 0
    abandonments: int = 0
    queue_clears: int = 0
    lost_demand_total: int = 0
    browse_without_join: int = 0
    customer_left_voluntarily: int = 0
    lost_join_opportunities: int = 0
    avg_wait_minutes: int | None = None
    avg_serve_minutes: int | None = None
    min_wait_minutes: int | None = None
    max_wait_minutes: int | None = None
    min_serve_minutes: int | None = None
    max_serve_minutes: int | None = None
    conversion_rate_pct: float | None = None
    customers_helped: int = 0
    leave_rate_pct: float | None = None


class TimeBucket(SQLModel):
    label: str
    value: int = 0
    secondary: int = 0
    hour: int | None = None
    is_estimated: bool = False


class AnalyticsHighlight(SQLModel):
    """One plain-language fact for the dashboard."""

    id: str
    title: str
    value: str
    detail: str
    tone: str = "neutral"  # good | caution | neutral | bad


class AnalyticsPeakSlot(SQLModel):
    """Best or worst slot for a metric."""

    kind: str  # join | leave | wait | day
    direction: str  # best | worst
    label: str
    metric_label: str
    metric_value: str
    explanation: str


class AnalyticsStreaks(SQLModel):
    active_days: int = 0
    quiet_days: int = 0
    current_busy_streak_days: int = 0
    longest_busy_streak_days: int = 0
    times_queue_cleared: int = 0
    busiest_day_name: str | None = None
    quietest_day_name: str | None = None


class AnalyticsComparison(SQLModel):
    label: str
    period_a_label: str
    period_a_value: str
    period_b_label: str
    period_b_value: str
    verdict: str


class ProviderAnalyticsServiceLine(SQLModel):
    service_item_id: uuid.UUID
    service_name: str
    joins: int = 0
    completed: int = 0
    cancelled: int = 0
    no_show: int = 0


class ProviderAnalyticsPublic(SQLModel):
    provider_id: uuid.UUID
    service_item_id: uuid.UUID | None = None
    range_days: int = 30
    since: datetime | None = None
    until: datetime | None = None
    data_quality: str = "empty"
    uses_estimates: bool = False
    narrative_summary: str = ""
    summary: ProviderAnalyticsSummary
    hourly_activity: list[TimeBucket] = Field(default_factory=list)
    hourly_leaves: list[TimeBucket] = Field(default_factory=list)
    daily_trend: list[TimeBucket] = Field(default_factory=list)
    daily_leaves: list[TimeBucket] = Field(default_factory=list)
    weekday_activity: list[TimeBucket] = Field(default_factory=list)
    weekday_leaves: list[TimeBucket] = Field(default_factory=list)
    ticket_outcomes: dict[str, int] = Field(default_factory=dict)
    join_sources: dict[str, int] = Field(default_factory=dict)
    service_lines: list[ProviderAnalyticsServiceLine] = Field(default_factory=list)
    insights: list[str] = Field(default_factory=list)
    highlights: list[AnalyticsHighlight] = Field(default_factory=list)
    peak_slots: list[AnalyticsPeakSlot] = Field(default_factory=list)
    streaks: AnalyticsStreaks = Field(default_factory=AnalyticsStreaks)
    comparisons: list[AnalyticsComparison] = Field(default_factory=list)
    peak_hour: int | None = None
    quiet_hour: int | None = None
    peak_leave_hour: int | None = None


# --- KYC ---


class ProviderDocument(SQLModel, table=True):
    __tablename__ = "provider_document"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    provider_id: uuid.UUID = Field(foreign_key="provider.id", ondelete="CASCADE", index=True)
    uploaded_by_user_id: uuid.UUID = Field(
        foreign_key="user.id",
        ondelete="CASCADE",
    )
    filename: str = Field(max_length=255)
    content_type: str = Field(max_length=120)
    # Cloudinary ``public_id`` (legacy column name kept to avoid a migration).
    storage_relpath: str = Field(max_length=500)
    resource_type: str = Field(default="raw", max_length=16)
    created_at: datetime | None = Field(
        default_factory=utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )


class ProviderDocumentPublic(SQLModel):
    id: uuid.UUID
    provider_id: uuid.UUID
    filename: str
    content_type: str
    created_at: datetime | None = None
    url: str


# --- Admin ---


class AdminAuditLog(SQLModel, table=True):
    __tablename__ = "admin_audit_log"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    actor_user_id: uuid.UUID = Field(foreign_key="user.id", ondelete="CASCADE")
    action: str = Field(max_length=64)
    entity_type: str = Field(max_length=64)
    entity_id: uuid.UUID | None = None
    details: dict | None = Field(default=None, sa_column=Column(JSON, nullable=True))
    created_at: datetime | None = Field(
        default_factory=utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )


class ProviderRejectBody(SQLModel):
    reason: str = Field(min_length=1, max_length=1000)


class AdminUserRow(SQLModel):
    id: uuid.UUID
    email: EmailStr
    phone_number: str | None = None
    is_active: bool
    is_suspended: bool
    user_type: str


# --- OTP login stub (US-SYS-00) ---


class EmailOtpChallenge(SQLModel, table=True):
    __tablename__ = "email_otp_challenge"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    email: str = Field(index=True, max_length=255)
    code_hash: str = Field(max_length=128)
    expires_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
    consumed_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    created_at: datetime | None = Field(
        default_factory=utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )


class OtpRequest(SQLModel):
    email: EmailStr


class OtpVerify(SQLModel):
    email: EmailStr
    code: str = Field(min_length=4, max_length=10)


# --- Shared ---


class Message(SQLModel):
    message: str


class Token(SQLModel):
    access_token: str
    token_type: str = "bearer"


class TokenPayload(SQLModel):
    sub: str | None = None


class NewPassword(SQLModel):
    token: str
    new_password: str = Field(min_length=8, max_length=128)
