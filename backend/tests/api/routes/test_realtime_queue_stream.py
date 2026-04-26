import json
import uuid
from decimal import Decimal
from urllib.parse import quote

from fastapi.testclient import TestClient
from sqlmodel import Session

from werefa.core.config import settings
from werefa.identity.infrastructure import repo as identity_repo


def _create_service(
    client: TestClient, db: Session, su_headers: dict[str, str]
) -> str:
    su = identity_repo.get_user_by_email(
        session=db, email=settings.FIRST_SUPERUSER
    )
    assert su is not None
    slug = f"rt-{uuid.uuid4().hex[:8]}"
    r = client.post(
        f"{settings.API_V1_STR}/providers/",
        headers=su_headers,
        json={"slug": slug, "biz_name": "RT", "owner_user_id": str(su.id)},
    )
    assert r.status_code == 200, r.text
    pid = r.json()["id"]
    r = client.post(
        f"{settings.API_V1_STR}/providers/{pid}/services/",
        headers=su_headers,
        json={"name": "Q", "avg_duration_minutes": 15, "price": "5.00"},
    )
    assert r.status_code == 200, r.text
    assert Decimal(r.json()["price"]) == Decimal("5.00")
    return str(r.json()["id"])


def test_queue_websocket_receives_v1_on_remote_join(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    normal_user_token_headers: dict[str, str],
) -> None:
    sid = _create_service(client, db, superuser_token_headers)
    r = client.post(
        f"{settings.API_V1_STR}/login/access-token",
        data={
            "username": settings.FIRST_SUPERUSER,
            "password": settings.FIRST_SUPERUSER_PASSWORD,
        },
    )
    assert r.status_code == 200, r.text
    raw_token = r.json()["access_token"]
    q = quote(raw_token, safe="")

    with client.websocket_connect(
        f"{settings.API_V1_STR}/ws/service-items/{sid}/stream?token={q}"
    ) as wsc:
        r2 = client.post(
            f"{settings.API_V1_STR}/service-items/{sid}/join",
            headers=normal_user_token_headers,
            json={},
        )
        assert r2.status_code == 200, r2.text
        got = wsc.receive_text()
        data = json.loads(got)
        assert data.get("v") == 1
        assert data.get("type") == "queue_updated"
        assert data.get("reason") == "join"
        assert data.get("service_item_id") == str(sid)
