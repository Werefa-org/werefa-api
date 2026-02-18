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
    BroadcastSeverity,
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
    )
    strikes: list["UserStrike"] = Relationship(
        back_populates="user", cascade_delete=True
    )
    notifications: list["Notification"] = Relationship(
        back_populates="user", cascade_delete=True
    )


class UserPublic(UserBase):
    id: uuid.UUID
    created_at: datetime | None = None
    joins_blocked_until: datetime | None = None
    notification_prefs: list[str] | None = None


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


class ProviderPublic(ProviderBase):
    id: uuid.UUID
    created_at: datetime | None = None
    ratings_count: int = 0
    rating_avg: float | None = None


class ProviderStaffPublic(ProviderPublic):
    """Staff/owner view: includes the rotating access code so staff can
    share it. Returned by ``GET /providers/{id}/access-code``."""

    access_code: str | None = None


class ProviderDiscoveryPublic(ProviderPublic):
    distance_m: int | None = None
    active_tickets: int = 0
    serving_tickets: int = 0
    estimated_wait_minutes: int | None = None
    load_factor: str | None = Field(default=None, max_length=16)


class ProviderDiscoveriesPublic(SQLModel):
    data: list[ProviderDiscoveryPublic]
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


# --- Service item (one FIFO line per row) ---


class ServiceItemBase(SQLModel):
    name: str = Field(min_length=1, max_length=120)
    avg_duration_minutes: int = Field(ge=1, le=24 * 60)
    price: Decimal = Field(sa_column=Column(Numeric(10, 2), nullable=False))
    is_active: bool = True


class ServiceItemCreate(ServiceItemBase):
    pass


class ServiceItemUpdate(SQLModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    avg_duration_minutes: int | None = Field(default=None, ge=1, le=24 * 60)
    price: Decimal | None = None
    is_active: bool | None = None


class ServiceItem(ServiceItemBase, table=True):
    __tablename__ = "service_item"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    provider_id: uuid.UUID = Field(foreign_key="provider.id", ondelete="CASCADE")
    next_ticket_number: int = Field(default=1, ge=1)

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


class QueueEntry(QueueEntryBase, table=True):
    __tablename__ = "queue_entry"
    __table_args__ = (
        Index(
            "ix_queue_entry_one_active_user",
            "user_id",
            unique=True,
            postgresql_where=text(
                "user_id IS NOT NULL AND (status)::text IN ('waiting','serving')"
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

    service_item: ServiceItem | None = Relationship(back_populates="queue_entries")
    user: User | None = Relationship(back_populates="queue_entries")


class QueueJoin(SQLModel):
    access_code: str | None = Field(default=None, max_length=6)


class WalkInCreate(SQLModel):
    guest_name: str | None = Field(default=None, max_length=100)


class TicketStatusUpdate(SQLModel):
    status: TicketStatus


class QueueEntryPublic(QueueEntryBase):
    id: uuid.UUID
    service_item_id: uuid.UUID
    user_id: uuid.UUID | None = None
    joined_at: datetime | None = None
    completed_at: datetime | None = None


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
    created_at: datetime | None = None


class BroadcastsPublic(SQLModel):
    data: list[BroadcastPublic]
    count: int


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

    user: User | None = Relationship(back_populates="notifications")


class NotificationPublic(NotificationBase):
    id: uuid.UUID
    ticket_id: uuid.UUID | None = None
    position: int | None = None
    created_at: datetime | None = None


class NotificationsPublic(SQLModel):
    data: list[NotificationPublic]
    count: int


class NotificationPrefsUpdate(SQLModel):
    """Body of ``PATCH /users/me/notifications``."""

    notification_prefs: list[str] = Field(
        description=(
            "Ordered list of channel keys (e.g. "
            "[\"websocket\",\"email\"]); the first deliverable channel "
            "wins per dispatch. Channels not recognised by the server "
            "are rejected with 400."
        ),
        min_length=1,
        max_length=8,
    )


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
