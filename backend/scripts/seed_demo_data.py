#!/usr/bin/env python3
"""Populate the database with realistic Ethiopian demo data (Addis Ababa & Adama).

Safe to re-run: upserts users/providers by fixed email/slug. Use --reset to wipe
demo rows first.

Usage (from backend/):

    uv run python scripts/seed_demo_data.py
    uv run python scripts/seed_demo_data.py --reset
    uv run python scripts/seed_demo_data.py --reset --skip-images

Demo logins (password equals email):

    user1@example.com … user5@example.com  (service seekers)
    provider1@example.com … provider15@example.com  (business owners)
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
    r"^(user|provider|seeker)\d+@example\.com$", re.IGNORECASE
)

# Remote join allowed within ~100 km (demo: no strict geofence)
JOIN_RADIUS_M = 100_000

# Curated stock photos (medical / clinic — not random placeholders)
IMG_HOSPITAL = (
    "https://images.unsplash.com/photo-1519494026892-80bbd2d6fd0d?w=800&q=85"
)
IMG_DENTAL = (
    "https://images.unsplash.com/photo-1606811971610-4486c4f1a5a1?w=800&q=85"
)
IMG_PHARMACY = (
    "https://images.unsplash.com/photo-1576602976037-17499c253023?w=800&q=85"
)
IMG_CLINIC = (
    "https://images.unsplash.com/photo-1629909613654-28e377c37baf?w=800&q=85"
)
IMG_LAB = (
    "https://images.unsplash.com/photo-1579154204601-01588f42e03a?w=800&q=85"
)

# (slug_suffix, biz_name, city, region, lat, lng, status, owner_index 1–15)
BUSINESSES: list[tuple[str, str, str, str, float, float, str, int]] = [
    (
        "tikur-anbessa-hospital",
        "Tikur Anbessa Specialized Hospital",
        "Addis Ababa",
        "Addis Ababa",
        9.0054,
        38.7636,
        VerificationStatus.verified.value,
        1,
    ),
    (
        "st-pauls-hospital",
        "St. Paul's Hospital Millennium Medical College",
        "Addis Ababa",
        "Addis Ababa",
        9.0102,
        38.7525,
        VerificationStatus.verified.value,
        2,
    ),
    (
        "myungsung-medical-center",
        "Myungsung Christian Medical Center",
        "Addis Ababa",
        "Addis Ababa",
        8.9932,
        38.8214,
        VerificationStatus.verified.value,
        3,
    ),
    (
        "bethezata-hospital",
        "Bethezata General Hospital",
        "Addis Ababa",
        "Addis Ababa",
        9.0325,
        38.7489,
        VerificationStatus.verified.value,
        4,
    ),
    (
        "lancet-hospital-bole",
        "Lancet General Hospital — Bole",
        "Addis Ababa",
        "Addis Ababa",
        9.0012,
        38.7898,
        VerificationStatus.verified.value,
        5,
    ),
    (
        "cmc-medical-center",
        "Catholic Medical Centre (CMC)",
        "Addis Ababa",
        "Addis Ababa",
        9.0123,
        38.7711,
        VerificationStatus.verified.value,
        6,
    ),
    (
        "hayat-hospital",
        "Hayat General Hospital",
        "Addis Ababa",
        "Addis Ababa",
        9.0145,
        38.8012,
        VerificationStatus.verified.value,
        7,
    ),
    (
        "american-medical-center",
        "American Medical Center",
        "Addis Ababa",
        "Addis Ababa",
        9.0088,
        38.7845,
        VerificationStatus.verified.value,
        8,
    ),
    (
        "menelik-hospital",
        "Menelik II Referral Hospital",
        "Addis Ababa",
        "Addis Ababa",
        9.0338,
        38.7485,
        VerificationStatus.verified.value,
        9,
    ),
    (
        "gandhi-memorial-hospital",
        "Gandhi Memorial Hospital",
        "Addis Ababa",
        "Addis Ababa",
        9.0201,
        38.7356,
        VerificationStatus.pending.value,
        10,
    ),
    (
        "bole-specialty-dental",
        "Bole Specialty Dental & Orthodontics",
        "Addis Ababa",
        "Addis Ababa",
        9.0156,
        38.7891,
        VerificationStatus.verified.value,
        11,
    ),
    (
        "guardian-pharmacy-bole",
        "Guardian Pharmacy — Bole Atlas",
        "Addis Ababa",
        "Addis Ababa",
        9.0188,
        38.7872,
        VerificationStatus.verified.value,
        12,
    ),
    (
        "adama-hospital-medical-college",
        "Adama Hospital Medical College",
        "Adama",
        "Oromia",
        8.5420,
        39.2673,
        VerificationStatus.verified.value,
        13,
    ),
    (
        "adama-referral-hospital",
        "Adama Referral Hospital",
        "Adama",
        "Oromia",
        8.5389,
        39.2701,
        VerificationStatus.verified.value,
        14,
    ),
    (
        "adama-family-clinic",
        "Adama Family Health Clinic",
        "Adama",
        "Oromia",
        8.5410,
        39.2655,
        VerificationStatus.rejected.value,
        15,
    ),
]

BIZ_PROFILE: dict[str, dict[str, object]] = {
    "tikur-anbessa-hospital": {
        "category": "health",
        "description": (
            "Ethiopia's largest public referral hospital (Black Lion). Outpatient "
            "queues for general medicine, referrals, and follow-up visits. Join "
            "remotely and wait comfortably — we call your number when a window opens."
        ),
        "address": "Lideta sub-city, near Addis Ababa University medical campus",
        "phone": "+251111262000",
        "show_phone_public": True,
        "website": "https://www.aau.edu.et",
        "biz_email": "outpatient@tikur-anbessa.demo",
        "access_code": "TASO01",
        "image_url": IMG_HOSPITAL,
    },
    "st-pauls-hospital": {
        "category": "health",
        "description": (
            "Teaching hospital with outpatient clinics, specialist consults, and "
            "diagnostic services. Virtual queue reduces crowding at the main gate."
        ),
        "address": "Gulele, near Mexico Square",
        "phone": "+251115535000",
        "show_phone_public": True,
        "access_code": "STPL02",
        "image_url": IMG_HOSPITAL,
    },
    "myungsung-medical-center": {
        "category": "health",
        "description": (
            "Private hospital known as Korean Hospital. General practice, surgery "
            "scheduling desk, and international patient services."
        ),
        "address": "Kirkos sub-city, Debre Zeit Road area",
        "phone": "+251115184000",
        "show_phone_public": True,
        "access_code": "MYUN03",
        "image_url": IMG_HOSPITAL,
    },
    "bethezata-hospital": {
        "category": "health",
        "description": (
            "Multi-specialty private hospital near Mexico. Cardiology, internal "
            "medicine, and same-day lab collection lines."
        ),
        "address": "Mexico, Bethezata Street",
        "phone": "+251115504000",
        "show_phone_public": True,
        "access_code": "BETH04",
        "image_url": IMG_HOSPITAL,
    },
    "lancet-hospital-bole": {
        "category": "health",
        "description": (
            "Modern private hospital in Bole. Emergency triage, outpatient visits, "
            "and maternity reception queues available on Werefa."
        ),
        "address": "Bole Road, near Atlas Hotel",
        "phone": "+251116184000",
        "show_phone_public": True,
        "access_code": "LANC05",
        "image_url": IMG_HOSPITAL,
    },
    "cmc-medical-center": {
        "category": "health",
        "description": (
            "Catholic Medical Centre outpatient and chronic care follow-up. Pharmacy "
            "on site; join the line before you arrive."
        ),
        "address": "Gulele, CMC area",
        "phone": "+251111550000",
        "show_phone_public": True,
        "access_code": "CMC006",
        "image_url": IMG_CLINIC,
    },
    "hayat-hospital": {
        "category": "health",
        "description": (
            "Private hospital with pediatrics, OB/GYN, and general outpatient desks. "
            "Peak hours 8:00–11:00 — remote queue recommended."
        ),
        "address": "Bole, Hayat area",
        "phone": "+251116394000",
        "show_phone_public": True,
        "access_code": "HAYA07",
        "image_url": IMG_HOSPITAL,
    },
    "american-medical-center": {
        "category": "health",
        "description": (
            "Outpatient clinic with family medicine and travel health services. "
            "English-friendly front desk."
        ),
        "address": "Old Airport, CMC Road",
        "phone": "+251116674000",
        "show_phone_public": True,
        "access_code": "AMC008",
        "image_url": IMG_CLINIC,
    },
    "menelik-hospital": {
        "category": "health",
        "description": (
            "Historic referral hospital at Piassa. General outpatient, TB clinic "
            "referrals, and pharmacy pickup coordination."
        ),
        "address": "Arada, Piassa",
        "phone": "+251111515000",
        "show_phone_public": True,
        "access_code": "MENE09",
        "image_url": IMG_HOSPITAL,
    },
    "gandhi-memorial-hospital": {
        "category": "health",
        "description": (
            "Public hospital — pending verification in this demo environment. "
            "Shows owner onboarding before going live on discovery."
        ),
        "address": "Addis Ketema",
        "access_code": "GAND10",
        "image_url": IMG_HOSPITAL,
    },
    "bole-specialty-dental": {
        "category": "health",
        "description": (
            "Dental and orthodontic clinic in Bole. Cleanings, fillings, consults, "
            "and braces adjustment appointments. Walk-ins accepted mornings."
        ),
        "address": "Bole, Cameroon Street area",
        "phone": "+251911300011",
        "show_phone_public": True,
        "access_code": "BOLE11",
        "image_url": IMG_DENTAL,
    },
    "guardian-pharmacy-bole": {
        "category": "health",
        "description": (
            "Licensed pharmacy — prescription dispensing, OTC advice, and short "
            "pharmacist consultations. Fast pickup line for repeat medications."
        ),
        "address": "Bole Atlas, ground floor retail",
        "phone": "+251911300012",
        "show_phone_public": True,
        "access_code": "PHRM12",
        "image_url": IMG_PHARMACY,
    },
    "adama-hospital-medical-college": {
        "category": "health",
        "description": (
            "Major teaching hospital in Adama (Nazret). Outpatient pavilion handles "
            "hundreds of visits daily — use Werefa to hold your place before travel."
        ),
        "address": "Adama, Hospital Road",
        "phone": "+251221110000",
        "show_phone_public": True,
        "access_code": "ADMC13",
        "image_url": IMG_HOSPITAL,
    },
    "adama-referral-hospital": {
        "category": "health",
        "description": (
            "Regional referral hospital for East Shewa zone. General outpatient, "
            "maternal health intake, and lab sample drop-off queues."
        ),
        "address": "Adama city center, referral gate",
        "phone": "+251221120000",
        "show_phone_public": True,
        "access_code": "ADRF14",
        "image_url": IMG_HOSPITAL,
    },
    "adama-family-clinic": {
        "category": "health",
        "description": (
            "Rejected demo application — illustrates verification rejection UX for "
            "owners (incomplete license upload)."
        ),
        "address": "Adama, Kebele 05",
        "access_code": "ADFC15",
        "image_url": IMG_CLINIC,
    },
}

SERVICE_LINES: dict[str, list[tuple[str, int, str, str]]] = {
    # name, minutes, price ETB, description
    "hospital_outpatient": [
        (
            "General outpatient",
            35,
            "250.00",
            "First-come virtual line for GP assessment, vitals, and referral to specialty.",
        ),
        (
            "Follow-up visit",
            20,
            "150.00",
            "Return visit with prior chart — have your ticket number ready at Window 3.",
        ),
        (
            "Lab sample drop-off",
            10,
            "80.00",
            "Blood and urine collection queue; fasting labs before 10:00 AM.",
        ),
    ],
    "hospital_specialist": [
        (
            "Specialist consultation",
            40,
            "400.00",
            "Cardiology, orthopedics, or surgery clinic — referral letter required.",
        ),
        (
            "Emergency triage (non-critical)",
            25,
            "300.00",
            "Stable patients directed from ER waiting area to scheduled assessment.",
        ),
    ],
    "dental": [
        (
            "Dental checkup & cleaning",
            40,
            "450.00",
            "Exam, scaling, and treatment plan with the duty dentist.",
        ),
        (
            "Toothache / urgent consult",
            25,
            "350.00",
            "Same-day pain and swelling assessment.",
        ),
        (
            "Orthodontic adjustment",
            30,
            "500.00",
            "Braces follow-up — appointment strongly recommended.",
        ),
    ],
    "pharmacy": [
        (
            "Prescription pickup",
            8,
            "0.00",
            "Have your prescription code or paper ready at the counter.",
        ),
        (
            "Pharmacist consultation",
            15,
            "120.00",
            "Short consult for OTC selection or dosage questions.",
        ),
    ],
    "clinic": [
        (
            "GP clinic visit",
            25,
            "280.00",
            "General complaints, prescriptions, and sick notes.",
        ),
        (
            "Chronic care refill",
            15,
            "180.00",
            "Diabetes, hypertension, and asthma repeat prescriptions.",
        ),
    ],
}

SERVICE_LINE_META: dict[str, dict[str, object]] = {
    "hospital_outpatient": {
        "category": "health",
        "requirements": "National ID or passport. Prior referral if specialist-directed.",
        "allow_vip": True,
        "vip_code": "VIPLINE",
    },
    "dental": {
        "category": "health",
        "requirements": "Arrive 10 minutes early. Children under 12 with guardian.",
        "allow_vip": True,
        "vip_code": "VIPDENT",
    },
}

BIZ_SERVICE_KEY: dict[str, str] = {
    "tikur-anbessa-hospital": "hospital_outpatient",
    "st-pauls-hospital": "hospital_outpatient",
    "myungsung-medical-center": "hospital_specialist",
    "bethezata-hospital": "hospital_outpatient",
    "lancet-hospital-bole": "hospital_specialist",
    "cmc-medical-center": "clinic",
    "hayat-hospital": "hospital_outpatient",
    "american-medical-center": "clinic",
    "menelik-hospital": "hospital_outpatient",
    "gandhi-memorial-hospital": "hospital_outpatient",
    "bole-specialty-dental": "dental",
    "guardian-pharmacy-bole": "pharmacy",
    "adama-hospital-medical-college": "hospital_outpatient",
    "adama-referral-hospital": "hospital_outpatient",
    "adama-family-clinic": "clinic",
}

# Flagship queue demo (Adama Hospital Medical College — busy outpatient line)
FLAGSHIP_SLUG = "adama-hospital-medical-college"

LINE_CHAT_SAMPLES: list[tuple[str, str]] = [
    (
        "Welcome to Adama Hospital Medical College outpatient queue. "
        "Your number will appear on the screen near Window A.",
        "info",
    ),
    (
        "Estimated wait today: 25–40 minutes. Please stay within the waiting hall.",
        "info",
    ),
    (
        "Lab patients: fasting blood work is collected until 10:30 AM only.",
        "info",
    ),
    (
        "Window A is now serving tickets 12–15. Please listen for your number.",
        "info",
    ),
]

SEEKER_PROFILES: list[tuple[str, str, str]] = [
    ("user1@example.com", "Hanna Bekele", "+251911100001"),
    ("user2@example.com", "Samuel Tadesse", "+251911100002"),
    ("user3@example.com", "Meron Assefa", "+251911100003"),
    ("user4@example.com", "Daniel Girma", "+251911100004"),
    ("user5@example.com", "Selamawit Haile", "+251911100005"),
]

PROVIDER_NAMES: list[str] = [
    "Dr. Abebe Kebede",
    "Dr. Sara Mekonnen",
    "Dr. Yonas Haile",
    "Dr. Ruth Tesfaye",
    "Dr. Michael Lemma",
    "Sister Martha Assefa",
    "Dr. Elias Worku",
    "Dr. Naomi Desta",
    "Dr. Getachew Alemu",
    "Dr. Bethlehem Negash",
    "Dr. Fitsum Berhanu",
    "PharmD. Liya Solomon",
    "Dr. Tewodros Gemechu",
    "Dr. Almaz Demissie",
    "Dr. Kalkidan Feyisa",
]


def _demo_password(email: str) -> str:
    return email


def _maybe_upload_avatar(
    session: Session,
    *,
    folder: str,
    seed: str,
    entity,
    image_url: str | None = None,
) -> None:
    if SKIP_IMAGES or not settings.cloudinary_configured:
        return
    try:
        url = image_url or f"https://picsum.photos/seed/{seed}/400/400"
        resp = httpx.get(url, timeout=45.0, follow_redirects=True)
        resp.raise_for_status()
        data = resp.content
        if not data:
            return
        stored = cloudinary_storage.upload_public_image(
            data=data,
            folder=folder,
            asset_name="logo",
        )
        entity.profile_image_public_id = stored.public_id
        entity.profile_image_resource_type = stored.resource_type
        session.add(entity)
    except Exception as exc:
        logger.warning("Image upload skipped for %s: %s", seed, exc)


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
        image_url=None,
    )
    session.commit()
    session.refresh(user)
    return user


def _apply_provider_profile(
    p: Provider, *, slug_suffix: str, city: str, region: str
) -> None:
    meta = BIZ_PROFILE.get(slug_suffix, {})
    p.city = city
    p.region = region
    p.category = str(meta.get("category") or "health")
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
    region: str,
    lat: float,
    lng: float,
    status: str,
    owner: User,
) -> Provider:
    full_slug = f"{DEMO_SLUG_PREFIX}{slug}"
    existing = provider_repo.get_provider_by_slug(session=session, slug=full_slug)
    rejection = (
        "Upload valid trade license and medical facility registration to re-apply."
        if status == VerificationStatus.rejected.value
        else None
    )
    meta = BIZ_PROFILE.get(slug, {})
    if existing is None:
        body = ProviderCreate(
            slug=full_slug,
            biz_name=biz_name,
            latitude=lat,
            longitude=lng,
            join_radius_m=JOIN_RADIUS_M,
            is_open=True,
            is_paused=False,
            is_private=False,
            owner_user_id=owner.id,
            region=region,
            city=city,
            category=str(meta.get("category") or "health"),
            description=meta.get("description"),  # type: ignore[arg-type]
            address=meta.get("address"),  # type: ignore[arg-type]
        )
        auto_verify = status == VerificationStatus.verified.value
        p = provider_repo.create_provider(
            session=session, body=body, auto_verify=auto_verify
        )
        p.verification_status = status
        if rejection:
            p.last_rejection_reason = rejection
        session.add(p)
        session.commit()
        session.refresh(p)
        logger.info("Created provider %s (%s)", full_slug, status)
    else:
        p = existing
        p.biz_name = biz_name
        p.latitude = lat
        p.longitude = lng
        p.join_radius_m = JOIN_RADIUS_M
        p.verification_status = status
        p.last_rejection_reason = rejection
        p.is_open = True
        p.is_paused = False
        session.add(p)
        session.commit()
        session.refresh(p)
        logger.info("Updated provider %s", full_slug)

    _apply_provider_profile(p, slug_suffix=slug, city=city, region=region)
    session.add(p)
    session.commit()
    session.refresh(p)

    if provider_repo.get_membership(
        session=session, provider_id=p.id, user_id=owner.id
    ) is None:
        session.add(
            ProviderMembership(
                provider_id=p.id,
                user_id=owner.id,
                role=MembershipRole.owner.value,
            )
        )
        session.commit()

    image_url = meta.get("image_url")
    _maybe_upload_avatar(
        session,
        folder=f"{settings.CLOUDINARY_AVATARS_FOLDER}/providers/{p.id}",
        seed=full_slug,
        entity=p,
        image_url=str(image_url) if image_url else None,
    )
    session.commit()
    session.refresh(p)
    return p


def _upsert_services(
    session: Session, *, provider: Provider, slug_suffix: str
) -> list[ServiceItem]:
    key = BIZ_SERVICE_KEY.get(slug_suffix, "clinic")
    templates = SERVICE_LINES.get(key, SERVICE_LINES["clinic"])
    line_meta = SERVICE_LINE_META.get(key, {})
    items: list[ServiceItem] = []
    for idx, (name, minutes, price, desc) in enumerate(templates):
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
                description=desc,
            )
            session.add(row)
            session.commit()
            session.refresh(row)
        else:
            row.avg_duration_minutes = minutes
            row.price = Decimal(price)
            row.description = desc
            row.is_active = True
            session.add(row)
            session.commit()
            session.refresh(row)

        if idx == 0:
            if line_meta.get("category"):
                row.category = str(line_meta["category"])
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


def _seed_queue_ticket(
    session: Session,
    *,
    service: ServiceItem,
    seeker: User | None,
    ticket_number: int,
    status: str,
    priority: int = 0,
    guest_name: str | None = None,
    source: str | None = None,
) -> None:
    if seeker:
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
            user_id=seeker.id if seeker else None,
            guest_name=guest_name,
            ticket_number=ticket_number,
            status=status,
            source=source or TicketSource.remote_app.value,
            priority=priority,
        )
    )
    service.next_ticket_number = max(service.next_ticket_number, ticket_number + 1)
    session.add(service)
    session.commit()


def _seed_line_chat(session: Session, *, owner: User, service: ServiceItem) -> None:
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


def _seed_provider_ratings(session: Session, *, provider: Provider) -> None:
    """Aggregate counters for discovery cards (reviews require completed tickets)."""
    provider.ratings_count = 48
    provider.ratings_sum = 223  # ~4.6 average
    session.add(provider)
    session.commit()


def _seed_flagship_queue(
    session: Session,
    *,
    service: ServiceItem,
    seekers: list[User],
    owner: User,
) -> None:
    """Busy Adama Hospital outpatient line — demo centerpiece."""
    _seed_line_chat(session, owner=owner, service=service)

    # Five seekers waiting in order (positions 1–5)
    priorities = [10, 0, 0, 0, 0]  # user1 VIP priority
    for i, seeker in enumerate(seekers[:5]):
        _seed_queue_ticket(
            session,
            service=service,
            seeker=seeker,
            ticket_number=i + 1,
            status=TicketStatus.waiting.value,
            priority=priorities[i],
        )

    # Walk-in currently being served at counter
    _seed_queue_ticket(
        session,
        service=service,
        seeker=None,
        ticket_number=6,
        status=TicketStatus.serving.value,
        guest_name="Walk-in — Almaz T.",
        source=TicketSource.kiosk_walk_in.value,
    )

    # Next walk-in waiting behind
    _seed_queue_ticket(
        session,
        service=service,
        seeker=None,
        ticket_number=7,
        status=TicketStatus.waiting.value,
        guest_name="Walk-in — Counter B",
        source=TicketSource.kiosk_walk_in.value,
    )

    service.next_ticket_number = 8
    session.add(service)
    session.commit()
    logger.info(
        "Flagship queue on %s: tickets 1–5 waiting (user1 VIP), 6 serving, 7 walk-in",
        FLAGSHIP_SLUG,
    )


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
    logger.info("Removed demo providers, tickets, and demo @example.com users")


def seed(session: Session) -> None:
    init_db(session)
    logger.info("Admin: %s (from .env)", settings.FIRST_SUPERUSER)

    seekers = [
        _upsert_user(
            session,
            email=email,
            full_name=name,
            user_type=UserType.customer.value,
            phone_number=phone,
        )
        for email, name, phone in SEEKER_PROFILES
    ]

    providers: list[User] = []
    for i, name in enumerate(PROVIDER_NAMES, start=1):
        email = f"provider{i}@example.com"
        providers.append(
            _upsert_user(
                session,
                email=email,
                full_name=name,
                user_type=UserType.provider.value,
                phone_number=f"+251922{i:05d}",
            )
        )

    flagship_service: ServiceItem | None = None
    flagship_owner: User | None = None

    for slug_suffix, biz_name, city, region, lat, lng, status, owner_idx in BUSINESSES:
        owner = providers[owner_idx - 1]
        p = _upsert_provider(
            session,
            slug=slug_suffix,
            biz_name=biz_name,
            city=city,
            region=region,
            lat=lat,
            lng=lng,
            status=status,
            owner=owner,
        )
        if status != VerificationStatus.verified.value:
            continue

        services = _upsert_services(session, provider=p, slug_suffix=slug_suffix)
        if not services:
            continue

        primary = services[0]
        if slug_suffix == FLAGSHIP_SLUG:
            flagship_service = primary
            flagship_owner = owner
            _seed_provider_ratings(session, provider=p)

    if flagship_service and flagship_owner:
        _seed_flagship_queue(
            session,
            service=flagship_service,
            seekers=seekers,
            owner=flagship_owner,
        )

    # Staff: provider2 assists Tikur Anbessa (multi-site demo)
    tikur = provider_repo.get_provider_by_slug(
        session=session, slug=f"{DEMO_SLUG_PREFIX}tikur-anbessa-hospital"
    )
    if tikur and len(providers) >= 2:
        staff = providers[1]
        if provider_repo.get_membership(
            session=session, provider_id=tikur.id, user_id=staff.id
        ) is None:
            session.add(
                ProviderMembership(
                    provider_id=tikur.id,
                    user_id=staff.id,
                    role=MembershipRole.staff.value,
                )
            )
            session.commit()
            logger.info("Staff: %s on Tikur Anbessa", staff.email)

    logger.info("--- Demo accounts (password = email) ---")
    logger.info("Seekers: user1@example.com … user5@example.com")
    logger.info("Providers: provider1@example.com … provider15@example.com")
    logger.info("Admin: %s / %s", settings.FIRST_SUPERUSER, settings.FIRST_SUPERUSER_PASSWORD)
    logger.info("Discover slugs: %s*", DEMO_SLUG_PREFIX)
    logger.info("Flagship queue: %s%s (5 seekers waiting, busy line)", DEMO_SLUG_PREFIX, FLAGSHIP_SLUG)
    logger.info("Join radius: %s km on all demo providers", JOIN_RADIUS_M // 1000)
    logger.info("VIP on flagship: user1 has priority; code VIPLINE on outpatient service")


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
        help="Skip Cloudinary logo uploads (faster)",
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
