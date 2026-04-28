#!/usr/bin/env python3
"""Populate the database with realistic demo data (Addis Ababa & Adama).

Safe to re-run: upserts users/providers by fixed email/slug. Use --reset to wipe
demo rows first.

Usage (from backend/):

    uv run python scripts/seed_demo_data.py
    uv run python scripts/seed_demo_data.py --reset
    uv run python scripts/seed_demo_data.py --reset --skip-images

Demo logins (password equals email):

    seeker1@example.com / seeker1@example.com
    provider1@example.com / provider1@example.com
    … through seeker12 and provider8
    admin@example.com / adminpass123  (from .env FIRST_SUPERUSER_*)
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
from decimal import Decimal

import httpx
from sqlmodel import Session, col, delete, select

from werefa.core import cloudinary_storage
from werefa.core.config import settings
from werefa.core.db import engine, init_db
from werefa.core.security import get_password_hash
from werefa.identity.infrastructure import repo as identity_repo
from werefa.providers.infrastructure import repo as provider_repo
from werefa.shared.enums import (
    BroadcastSeverity,
    MembershipRole,
    TicketSource,
    TicketStatus,
    UserType,
    VerificationStatus,
)
from werefa.shared.models import (
    LineChatMessage,
    Notification,
    PositionPing,
    Provider,
    ProviderCreate,
    ProviderMembership,
    QueueEntry,
    Review,
    ServiceItem,
    User,
    UserCreate,
    UserStrike,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("seed_demo")

SKIP_IMAGES = False

DEMO_SLUG_PREFIX = "demo-"
DEMO_EMAIL_PATTERN = re.compile(
    r"^(seeker|provider)\d+@example\.com$", re.IGNORECASE
)

# (slug_suffix, biz_name, city, lat, lng, status, owner_index)
BUSINESSES: list[tuple[str, str, str, float, float, str, int]] = [
    (
        "addis-bole-dental",
        "Bole Smile Dental",
        "Addis Ababa",
        9.0108,
        38.7613,
        VerificationStatus.verified.value,
        1,
    ),
    (
        "addis-kazanchis-pharmacy",
        "Kazanchis Care Pharmacy",
        "Addis Ababa",
        9.0165,
        38.7689,
        VerificationStatus.verified.value,
        2,
    ),
    (
        "addis-merkato-auto",
        "Merkato Quick Auto",
        "Addis Ababa",
        9.0301,
        38.7418,
        VerificationStatus.pending.value,
        3,
    ),
    (
        "addis-piassa-salon",
        "Piassa Style Salon",
        "Addis Ababa",
        9.0334,
        38.7521,
        VerificationStatus.verified.value,
        4,
    ),
    (
        "addis-cmc-clinic",
        "CMC Community Clinic",
        "Addis Ababa",
        9.0089,
        38.7638,
        VerificationStatus.rejected.value,
        5,
    ),
    (
        "adama-city-hospital",
        "Adama City Hospital — Outpatient",
        "Adama",
        8.5412,
        39.2684,
        VerificationStatus.verified.value,
        6,
    ),
    (
        "adama-beauty-lounge",
        "Adama Beauty Lounge",
        "Adama",
        8.5391,
        39.2711,
        VerificationStatus.pending.value,
        7,
    ),
    (
        "adama-telecom-center",
        "Adama Telecom Service Desk",
        "Adama",
        8.5425,
        39.2650,
        VerificationStatus.verified.value,
        8,
    ),
]

# Extended provider profile + join access code (shown on provider queue board)
BIZ_PROFILE: dict[str, dict[str, object]] = {
    "addis-bole-dental": {
        "category": "health",
        "description": "Family dental clinic in Bole. Walk-ins welcome; remote queue for checkups.",
        "address": "Bole Road, near Friendship Mall",
        "phone": "+251911200001",
        "show_phone_public": True,
        "website": "https://example.com/bole-dental",
        "biz_email": "frontdesk@bolesmile.demo",
        "access_code": "BOLE01",
    },
    "addis-kazanchis-pharmacy": {
        "category": "health",
        "description": "Prescriptions, OTC medicines, and quick pharmacist consults.",
        "address": "Kazanchis, Churchill Avenue",
        "phone": "+251911200002",
        "show_phone_public": True,
        "access_code": "PHARM02",
    },
    "addis-merkato-auto": {
        "category": "automotive",
        "description": "Oil changes and inspections — pending verification for demo.",
        "address": "Merkato, main garage row",
        "access_code": "AUTO03",
    },
    "addis-piassa-salon": {
        "category": "beauty",
        "description": "Haircuts and styling in the heart of Piassa.",
        "address": "Piassa, Station area",
        "phone": "+251911200004",
        "show_phone_public": True,
        "access_code": "SALON4",
    },
    "addis-cmc-clinic": {
        "category": "health",
        "description": "Rejected demo business — shows owner rejection reason in app.",
        "address": "CMC area",
        "access_code": "CMC005",
    },
    "adama-city-hospital": {
        "category": "health",
        "description": "Outpatient lines for GP visits and specialist referrals.",
        "address": "Adama main hospital gate",
        "phone": "+251922200006",
        "show_phone_public": True,
        "access_code": "ADAM06",
    },
    "adama-beauty-lounge": {
        "category": "beauty",
        "description": "Beauty services — pending KYC in demo.",
        "address": "Adama city center",
        "access_code": "BEAU07",
    },
    "adama-telecom-center": {
        "category": "services",
        "description": "SIM registration and billing support desks.",
        "address": "Adama telecom plaza",
        "phone": "+251922200008",
        "show_phone_public": True,
        "access_code": "TEL08",
    },
}

SERVICE_LINES: dict[str, list[tuple[str, int, str]]] = {
    "dental": [
        ("Dental checkup", 25, "200.00"),
        ("Teeth cleaning", 35, "350.00"),
        ("Consultation", 15, "150.00"),
    ],
    "pharmacy": [
        ("Prescription pickup", 10, "0.00"),
        ("Health consultation", 20, "100.00"),
    ],
    "auto": [
        ("Oil change", 30, "800.00"),
        ("General inspection", 45, "500.00"),
    ],
    "salon": [
        ("Haircut", 30, "250.00"),
        ("Styling", 45, "400.00"),
    ],
    "clinic": [
        ("GP visit", 20, "300.00"),
        ("Lab sample", 10, "150.00"),
    ],
    "hospital": [
        ("Outpatient ticket", 40, "250.00"),
        ("Specialist referral", 30, "400.00"),
        ("Follow-up", 20, "180.00"),
    ],
    "beauty": [
        ("Manicure", 40, "200.00"),
        ("Facial", 50, "450.00"),
    ],
    "telecom": [
        ("SIM registration", 15, "0.00"),
        ("Billing support", 20, "0.00"),
    ],
}

# Optional per-line metadata (description, category, VIP on primary line)
SERVICE_LINE_META: dict[str, dict[str, object]] = {
    "dental": {
        "category": "health",
        "description": "Routine dental visit — share location when you are near the front.",
        "allow_vip": True,
        "vip_code": "VIPBOLE",
    },
    "hospital": {
        "category": "health",
        "description": "General outpatient queue.",
        "requirements": "Bring ID and prior referral if applicable.",
    },
    "telecom": {
        "category": "services",
        "description": "SIM and billing desk.",
    },
}

BIZ_SERVICE_KEY = {
    "addis-bole-dental": "dental",
    "addis-kazanchis-pharmacy": "pharmacy",
    "addis-merkato-auto": "auto",
    "addis-piassa-salon": "salon",
    "addis-cmc-clinic": "clinic",
    "adama-city-hospital": "hospital",
    "adama-beauty-lounge": "beauty",
    "adama-telecom-center": "telecom",
}

# Sample line-chat messages (owner-style) for verified businesses
LINE_CHAT_SAMPLES: list[tuple[str, str]] = [
    ("Welcome! You're in our virtual line — we'll call your number when it's your turn.", "info"),
    ("Today's wait is about 15–25 minutes. Thank you for your patience.", "info"),
    ("Bathroom and water are available in the waiting area.", "info"),
]


def _demo_password(email: str) -> str:
    return email


def _avatar_seed(key: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]", "", key)[:40]


def _maybe_upload_avatar(session: Session, *, folder: str, seed: str, entity) -> None:
    if SKIP_IMAGES or not settings.cloudinary_configured:
        return
    try:
        url = f"https://picsum.photos/seed/{_avatar_seed(seed)}/400/400"
        resp = httpx.get(url, timeout=30.0, follow_redirects=True)
        data = resp.content
        if not data:
            return
        stored = cloudinary_storage.upload_public_image(
            data=data,
            folder=folder,
            asset_name="avatar.jpg",
        )
        entity.profile_image_public_id = stored.public_id
        entity.profile_image_resource_type = stored.resource_type
        session.add(entity)
    except Exception as exc:
        logger.warning("Avatar upload skipped for %s: %s", seed, exc)


def _upsert_user(
    session: Session,
    *,
    email: str,
    full_name: str,
    user_type: str,
    phone_number: str | None = None,
) -> User:
    user = identity_repo.get_user_by_email(session=session, email=email)
    password = _demo_password(email)
    if user is None:
        user = identity_repo.create_user(
            session=session,
            user_create=UserCreate(
                email=email,
                password=password,
                full_name=full_name,
                user_type=user_type,
                phone_number=phone_number,
            ),
        )
        logger.info("Created user %s", email)
    else:
        user.full_name = full_name
        user.user_type = user_type
        user.phone_number = phone_number
        user.hashed_password = get_password_hash(password)
        user.is_active = True
        user.is_suspended = False
        session.add(user)
        session.commit()
        session.refresh(user)
        logger.info("Updated user %s", email)

    _maybe_upload_avatar(
        session,
        folder=f"{settings.CLOUDINARY_AVATARS_FOLDER}/users/{user.id}",
        seed=email,
        entity=user,
    )
    session.commit()
    session.refresh(user)
    return user


def _apply_provider_profile(p: Provider, *, slug_suffix: str, city: str) -> None:
    meta = BIZ_PROFILE.get(slug_suffix, {})
    p.city = city
    p.category = str(meta.get("category") or p.category or "services")
    p.description = meta.get("description")  # type: ignore[assignment]
    p.address = meta.get("address")  # type: ignore[assignment]
    p.phone = meta.get("phone")  # type: ignore[assignment]
    p.show_phone_public = bool(meta.get("show_phone_public", False))
    p.website = meta.get("website")  # type: ignore[assignment]
    p.biz_email = meta.get("biz_email")  # type: ignore[assignment]
    code = meta.get("access_code")
    if code:
        p.access_code = str(code)[:6]


def _upsert_provider(
    session: Session,
    *,
    slug: str,
    biz_name: str,
    city: str,
    lat: float,
    lng: float,
    status: str,
    owner: User,
) -> Provider:
    full_slug = f"{DEMO_SLUG_PREFIX}{slug}"
    existing = provider_repo.get_provider_by_slug(session=session, slug=full_slug)
    rejection = (
        "Demo seed: incomplete license paperwork."
        if status == VerificationStatus.rejected.value
        else None
    )
    if existing is None:
        body = ProviderCreate(
            slug=full_slug,
            biz_name=biz_name,
            latitude=lat,
            longitude=lng,
            join_radius_m=3000,
            is_open=True,
            is_paused=False,
            is_private=False,
            owner_user_id=owner.id,
        )
        auto_verify = status == VerificationStatus.verified.value
        p = provider_repo.create_provider(
            session=session, body=body, auto_verify=auto_verify
        )
        if status == VerificationStatus.rejected.value:
            p.verification_status = VerificationStatus.rejected.value
            p.last_rejection_reason = rejection
        elif status == VerificationStatus.pending.value:
            p.verification_status = VerificationStatus.pending.value
        session.add(p)
        session.commit()
        session.refresh(p)
        logger.info("Created provider %s (%s)", full_slug, status)
    else:
        p = existing
        p.biz_name = biz_name
        p.latitude = lat
        p.longitude = lng
        p.join_radius_m = 3000
        p.verification_status = status
        p.last_rejection_reason = rejection
        p.is_open = True
        session.add(p)
        session.commit()
        session.refresh(p)
        logger.info("Updated provider %s", full_slug)

    _apply_provider_profile(p, slug_suffix=slug, city=city)
    session.add(p)
    session.commit()
    session.refresh(p)

    membership = provider_repo.get_membership(
        session=session, provider_id=p.id, user_id=owner.id
    )
    if membership is None:
        session.add(
            ProviderMembership(
                provider_id=p.id,
                user_id=owner.id,
                role=MembershipRole.owner.value,
            )
        )
        session.commit()

    _maybe_upload_avatar(
        session,
        folder=f"{settings.CLOUDINARY_AVATARS_FOLDER}/providers/{p.id}",
        seed=full_slug,
        entity=p,
    )
    session.commit()
    session.refresh(p)
    return p


def _upsert_services(
    session: Session, *, provider: Provider, slug: str
) -> list[ServiceItem]:
    slug_suffix = slug.replace(DEMO_SLUG_PREFIX, "")
    key = BIZ_SERVICE_KEY.get(slug_suffix, "clinic")
    templates = SERVICE_LINES[key]
    line_meta = SERVICE_LINE_META.get(key, {})
    items: list[ServiceItem] = []
    for idx, (name, minutes, price) in enumerate(templates):
        row = session.exec(
            select(ServiceItem).where(
                ServiceItem.provider_id == provider.id,
                ServiceItem.name == name,
            )
        ).first()
        if row is None:
            row = ServiceItem(
                provider_id=provider.id,
                name=name,
                avg_duration_minutes=minutes,
                price=Decimal(price),
                is_active=True,
                next_ticket_number=1,
            )
            session.add(row)
            session.commit()
            session.refresh(row)
        else:
            row.avg_duration_minutes = minutes
            row.price = Decimal(price)
            row.is_active = True
            session.add(row)
            session.commit()

        if idx == 0:
            if line_meta.get("category"):
                row.category = str(line_meta["category"])
            if line_meta.get("description"):
                row.description = str(line_meta["description"])
            if line_meta.get("requirements"):
                row.requirements = str(line_meta["requirements"])
            row.allow_vip = bool(line_meta.get("allow_vip", False))
            if line_meta.get("vip_code"):
                row.vip_code = str(line_meta["vip_code"])
            row.is_paused = False
            row.is_private = False
            session.add(row)
            session.commit()

        items.append(row)
    return items


def _seed_queue_sample(
    session: Session,
    *,
    service: ServiceItem,
    seeker: User,
    ticket_number: int,
    priority: int = 0,
) -> None:
    """One waiting ticket per seeker (DB allows only one active ticket per user)."""
    active_elsewhere = session.exec(
        select(QueueEntry.id).where(
            QueueEntry.user_id == seeker.id,
            col(QueueEntry.status).in_(
                (TicketStatus.waiting.value, TicketStatus.serving.value)
            ),
        )
    ).first()
    if active_elsewhere:
        return
    exists = session.exec(
        select(QueueEntry).where(
            QueueEntry.service_item_id == service.id,
            QueueEntry.user_id == seeker.id,
            col(QueueEntry.status).in_(
                (TicketStatus.waiting.value, TicketStatus.serving.value)
            ),
        )
    ).first()
    if exists:
        return
    session.add(
        QueueEntry(
            service_item_id=service.id,
            user_id=seeker.id,
            ticket_number=ticket_number,
            status=TicketStatus.waiting.value,
            source=TicketSource.remote_app.value,
            priority=priority,
        )
    )
    service.next_ticket_number = max(service.next_ticket_number, ticket_number + 1)
    session.add(service)
    session.commit()


def _seed_walk_in_serving(
    session: Session,
    *,
    service: ServiceItem,
    ticket_number: int,
    guest_name: str = "Walk-in guest",
) -> None:
    exists = session.exec(
        select(QueueEntry).where(
            QueueEntry.service_item_id == service.id,
            QueueEntry.ticket_number == ticket_number,
            col(QueueEntry.status).in_(
                (TicketStatus.waiting.value, TicketStatus.serving.value)
            ),
        )
    ).first()
    if exists:
        return
    session.add(
        QueueEntry(
            service_item_id=service.id,
            user_id=None,
            guest_name=guest_name,
            ticket_number=ticket_number,
            status=TicketStatus.serving.value,
            source=TicketSource.kiosk_walk_in.value,
        )
    )
    service.next_ticket_number = max(service.next_ticket_number, ticket_number + 1)
    session.add(service)
    session.commit()


def _seed_line_chat(
    session: Session,
    *,
    owner: User,
    service: ServiceItem,
) -> None:
    for body, _severity in LINE_CHAT_SAMPLES:
        exists = session.exec(
            select(LineChatMessage.id).where(
                LineChatMessage.service_item_id == service.id,
                LineChatMessage.body == body,
            )
        ).first()
        if exists:
            continue
        session.add(
            LineChatMessage(
                service_item_id=service.id,
                author_user_id=owner.id,
                body=body,
            )
        )
    session.commit()


def reset_demo_data(session: Session) -> None:
    demo_provider_ids = list(
        session.exec(
            select(Provider.id).where(col(Provider.slug).like(f"{DEMO_SLUG_PREFIX}%"))
        ).all()
    )
    demo_user_ids = [
        u.id
        for u in session.exec(select(User)).all()
        if DEMO_EMAIL_PATTERN.match(u.email)
    ]

    service_ids: list = []
    ticket_ids: list = []

    if demo_provider_ids:
        service_ids = list(
            session.exec(
                select(ServiceItem.id).where(
                    col(ServiceItem.provider_id).in_(demo_provider_ids)
                )
            ).all()
        )
        if service_ids:
            ticket_ids = list(
                session.exec(
                    select(QueueEntry.id).where(
                        col(QueueEntry.service_item_id).in_(service_ids)
                    )
                ).all()
            )
            if ticket_ids:
                session.exec(
                    delete(PositionPing).where(
                        col(PositionPing.ticket_id).in_(ticket_ids)
                    )
                )
                session.exec(
                    delete(Notification).where(
                        col(Notification.ticket_id).in_(ticket_ids)
                    )
                )
            session.exec(
                delete(QueueEntry).where(
                    col(QueueEntry.service_item_id).in_(service_ids)
                )
            )
            session.exec(
                delete(ServiceItem).where(col(ServiceItem.id).in_(service_ids))
            )
            session.exec(
                delete(LineChatMessage).where(
                    col(LineChatMessage.service_item_id).in_(service_ids)
                )
            )
        session.exec(
            delete(Review).where(col(Review.provider_id).in_(demo_provider_ids))
        )
        session.exec(
            delete(ProviderMembership).where(
                col(ProviderMembership.provider_id).in_(demo_provider_ids)
            )
        )
        session.exec(delete(Provider).where(col(Provider.id).in_(demo_provider_ids)))

    if demo_user_ids:
        session.exec(
            delete(Notification).where(col(Notification.user_id).in_(demo_user_ids))
        )
        session.exec(
            delete(UserStrike).where(col(UserStrike.user_id).in_(demo_user_ids))
        )
        session.exec(
            delete(QueueEntry).where(col(QueueEntry.user_id).in_(demo_user_ids))
        )
        session.exec(delete(User).where(col(User.id).in_(demo_user_ids)))

    session.commit()
    logger.info("Removed demo providers, tickets, broadcasts, and demo @example.com users")


def seed(session: Session) -> None:
    init_db(session)
    logger.info("Ensured admin user %s exists", settings.FIRST_SUPERUSER)

    seekers: list[User] = []
    for i in range(1, 13):
        email = f"seeker{i}@example.com"
        seekers.append(
            _upsert_user(
                session,
                email=email,
                full_name=f"Demo Seeker {i}",
                user_type=UserType.customer.value,
                phone_number=f"+25191100{i:04d}",
            )
        )

    providers: list[User] = []
    for i in range(1, 9):
        email = f"provider{i}@example.com"
        providers.append(
            _upsert_user(
                session,
                email=email,
                full_name=f"Demo Provider {i}",
                user_type=UserType.provider.value,
                phone_number=f"+25192200{i:04d}",
            )
        )

    verified_services: list[tuple[ServiceItem, Provider, User]] = []
    bole_primary: ServiceItem | None = None

    for slug_suffix, biz_name, city, lat, lng, status, owner_idx in BUSINESSES:
        owner = providers[owner_idx - 1]
        p = _upsert_provider(
            session,
            slug=slug_suffix,
            biz_name=biz_name,
            city=city,
            lat=lat,
            lng=lng,
            status=status,
            owner=owner,
        )
        if status == VerificationStatus.verified.value:
            services = _upsert_services(session, provider=p, slug=slug_suffix)
            if services:
                verified_services.append((services[0], p, owner))
                _seed_line_chat(session, owner=owner, service=services[0])
                if slug_suffix == "addis-bole-dental":
                    bole_primary = services[0]

    # Staff: provider2 helps provider1's Bole dental (second membership)
    bole = provider_repo.get_provider_by_slug(
        session=session, slug=f"{DEMO_SLUG_PREFIX}addis-bole-dental"
    )
    if bole and len(providers) >= 2:
        staff = providers[1]
        if provider_repo.get_membership(
            session=session, provider_id=bole.id, user_id=staff.id
        ) is None:
            session.add(
                ProviderMembership(
                    provider_id=bole.id,
                    user_id=staff.id,
                    role=MembershipRole.staff.value,
                )
            )
            session.commit()
            logger.info("Added %s as staff on Bole dental", staff.email)

    ticket_base = 1
    for idx, (svc, _p, _owner) in enumerate(
        verified_services[: min(8, len(seekers))]
    ):
        priority = 5 if idx == 0 and svc.allow_vip else 0
        _seed_queue_sample(
            session,
            service=svc,
            seeker=seekers[idx],
            ticket_number=ticket_base,
            priority=priority,
        )
        ticket_base += 1

    # Extra seekers on Bole line (positions 2–3) for a busier queue demo
    if bole_primary and len(seekers) >= 10:
        for seeker, num in ((seekers[8], ticket_base), (seekers[9], ticket_base + 1)):
            _seed_queue_sample(
                session,
                service=bole_primary,
                seeker=seeker,
                ticket_number=num,
            )
        ticket_base += 2
        _seed_walk_in_serving(
            session,
            service=bole_primary,
            ticket_number=ticket_base,
            guest_name="Walk-in — counter 1",
        )

    logger.info("--- Demo accounts (password = email) ---")
    logger.info("Seekers: seeker1@example.com … seeker12@example.com")
    logger.info("Providers: provider1@example.com … provider8@example.com")
    logger.info(
        "Admin: %s / %s",
        settings.FIRST_SUPERUSER,
        settings.FIRST_SUPERUSER_PASSWORD,
    )
    logger.info("Business slugs: %s*", DEMO_SLUG_PREFIX)
    logger.info("Bole dental VIP code: VIPBOLE (first line, seeker1 has priority ticket)")
    logger.info("Join access codes: see BIZ_PROFILE in seed script (e.g. BOLE01)")


def main() -> None:
    global SKIP_IMAGES
    parser = argparse.ArgumentParser(description="Seed Werefa demo data")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Delete demo providers/users before seeding",
    )
    parser.add_argument(
        "--skip-images",
        action="store_true",
        help="Skip Cloudinary avatar uploads (faster)",
    )
    args = parser.parse_args()
    SKIP_IMAGES = args.skip_images

    with Session(engine) as session:
        if args.reset:
            reset_demo_data(session)
        seed(session)

    logger.info("Done.")


if __name__ == "__main__":
    main()
    sys.exit(0)
