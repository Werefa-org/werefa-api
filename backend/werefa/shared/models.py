import uuid
from datetime import datetime, timezone
from decimal import Decimal

from pydantic import EmailStr
from sqlalchemy import Column, DateTime, Index, Numeric, UniqueConstraint, text
from sqlmodel import Field, Relationship, SQLModel

from werefa.shared.enums import (
    MembershipRole,
    TicketStatus,
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


class UserCreate(UserBase):
    password: str = Field(min_length=8, max_length=128)


class UserRegister(SQLModel):
    email: EmailStr = Field(max_length=255)
    password: str = Field(min_length=8, max_length=128)
    full_name: str | None = Field(default=None, max_length=255)


class UserUpdate(UserBase):
    email: EmailStr | None = Field(default=None, max_length=255)  # type: ignore[assignment]
    password: str | None = Field(default=None, min_length=8, max_length=128)


class UserUpdateMe(SQLModel):
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
    provider_memberships: list["ProviderMembership"] = Relationship(
        back_populates="user", cascade_delete=True
    )
    queue_entries: list["QueueEntry"] = Relationship(
        back_populates="user",
        cascade_delete=False,
    )


class UserPublic(UserBase):
    id: uuid.UUID
    created_at: datetime | None = None


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
    access_code: str | None = Field(default=None, max_length=6)


class ProviderCreate(ProviderBase):
    owner_user_id: uuid.UUID | None = None


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
    created_at: datetime | None = Field(
        default_factory=utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    memberships: list["ProviderMembership"] = Relationship(
        back_populates="provider", cascade_delete=True
    )
    service_items: list["ServiceItem"] = Relationship(
        back_populates="provider", cascade_delete=True
    )


class ProviderPublic(ProviderBase):
    id: uuid.UUID
    created_at: datetime | None = None


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
    completed_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )

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
