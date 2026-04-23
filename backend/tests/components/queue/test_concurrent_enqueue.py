"""
Concurrent remote joins: one Session per thread, FIFO / unique ticket numbers,
and one active app ticket per user (including DB-level race with partial unique index).
"""
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from decimal import Decimal

from fastapi import HTTPException, status
from sqlmodel import Session

from tests.utils.utils import random_email, random_lower_string
from werefa.core.config import settings
from werefa.core.db import engine
from werefa.identity.infrastructure import repo as identity_repo
from werefa.providers.infrastructure import repo as provider_repo
from werefa.queue.application import service as queue_service
from werefa.service_items.infrastructure import repo as service_item_repo
from werefa.shared.models import (
    ProviderCreate,
    ServiceItemCreate,
    User,
    UserCreate,
)


def _provider_and_open_service(db: Session) -> uuid.UUID:
    owner = identity_repo.get_user_by_email(
        session=db, email=settings.FIRST_SUPERUSER
    )
    assert owner is not None
    p = provider_repo.create_provider(
        session=db,
        body=ProviderCreate(
            slug=f"conc-{uuid.uuid4().hex[:8]}",
            biz_name="Concurrent provider",
            owner_user_id=owner.id,
        ),
    )
    si = service_item_repo.create_service_item(
        session=db,
        provider_id=p.id,
        body=ServiceItemCreate(
            name="Service",
            avg_duration_minutes=15,
            price=Decimal("10.00"),
        ),
    )
    return si.id


def test_concurrent_remote_joins_distinct_sequential_tickets(
    db: Session,
) -> None:
    service_item_id = _provider_and_open_service(db)
    n = 8
    user_ids: list[uuid.UUID] = []
    for _ in range(n):
        u = identity_repo.create_user(
            session=db,
            user_create=UserCreate(
                email=random_email(),
                password=random_lower_string()[:12],
            ),
        )
        user_ids.append(u.id)

    def join_one(user_id: uuid.UUID) -> int:
        with Session(engine) as session:
            user = session.get(User, user_id)
            assert user is not None
            t = queue_service.join_queue_remote(
                session,
                service_item_id=service_item_id,
                user=user,
                access_code=None,
            )
            return t.ticket_number

    with ThreadPoolExecutor(max_workers=n) as ex:
        futures = [ex.submit(join_one, uid) for uid in user_ids]
        numbers = [f.result() for f in as_completed(futures)]

    assert len(numbers) == n
    assert len(set(numbers)) == n
    assert sorted(numbers) == list(range(1, n + 1))


def test_concurrent_double_join_same_user_one_conflict(
    db: Session,
) -> None:
    service_item_id = _provider_and_open_service(db)
    u = identity_repo.create_user(
        session=db,
        user_create=UserCreate(
            email=random_email(),
            password=random_lower_string()[:12],
        ),
    )

    def try_join() -> tuple[str, int | None]:
        with Session(engine) as session:
            user = session.get(User, u.id)
            assert user is not None
            try:
                t = queue_service.join_queue_remote(
                    session,
                    service_item_id=service_item_id,
                    user=user,
                    access_code=None,
                )
                return "ok", t.ticket_number
            except HTTPException as e:
                return "err", e.status_code

    with ThreadPoolExecutor(max_workers=2) as ex:
        results = list(ex.map(lambda _: try_join(), range(2)))

    oks = [r for r in results if r[0] == "ok"]
    errs = [r for r in results if r[0] == "err"]
    assert len(oks) == 1
    assert len(errs) == 1
    assert errs[0][1] == status.HTTP_409_CONFLICT
