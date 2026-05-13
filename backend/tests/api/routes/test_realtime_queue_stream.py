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
        assert data.get("status") == "waiting"
        assert data.get("position") == 1
        assert data.get("ticket_id") == r2.json()["id"]


def test_ticket_websocket_receives_ticket_status_update(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    normal_user_token_headers: dict[str, str],
) -> None:
    sid = _create_service(client, db, superuser_token_headers)
    join = client.post(
        f"{settings.API_V1_STR}/service-items/{sid}/join",
        headers=normal_user_token_headers,
        json={},
    )
    assert join.status_code == 200, join.text
    ticket_id = join.json()["id"]
    cn = client.post(
        f"{settings.API_V1_STR}/service-items/{sid}/call-next",
        headers=superuser_token_headers,
    )
    assert cn.status_code == 200, cn.text
    assert cn.json()["id"] == ticket_id
    bearer = normal_user_token_headers["Authorization"]
    raw_token = bearer.replace("Bearer ", "", 1)
    q = quote(raw_token, safe="")

    with client.websocket_connect(
        f"{settings.API_V1_STR}/ws/tickets/{ticket_id}/stream?token={q}"
    ) as wsc:
        update = client.patch(
            f"{settings.API_V1_STR}/service-items/{sid}/tickets/{ticket_id}/status",
            headers=superuser_token_headers,
            json={"status": "no_show"},
        )
        assert update.status_code == 200, update.text
        data = json.loads(wsc.receive_text())
        assert data.get("service_item_id") == sid
        assert data.get("ticket_id") == ticket_id
        assert data.get("status") == "no_show"
        assert data.get("position") is None
        assert data.get("reason") == "status_update"


def test_service_websocket_multiple_clients_get_same_event(
    client: TestClient,
    db: Session,
    superuser_token_headers: dict[str, str],
    normal_user_token_headers: dict[str, str],
) -> None:
    sid = _create_service(client, db, superuser_token_headers)
    login = client.post(
        f"{settings.API_V1_STR}/login/access-token",
        data={
            "username": settings.FIRST_SUPERUSER,
            "password": settings.FIRST_SUPERUSER_PASSWORD,
        },
    )
    assert login.status_code == 200, login.text
    raw_token = login.json()["access_token"]
    q = quote(raw_token, safe="")
    path = f"{settings.API_V1_STR}/ws/service-items/{sid}/stream?token={q}"

    with client.websocket_connect(path) as ws1:
        with client.websocket_connect(path) as ws2:
            join = client.post(
                f"{settings.API_V1_STR}/service-items/{sid}/join",
                headers=normal_user_token_headers,
                json={},
            )
            assert join.status_code == 200, join.text
            one = json.loads(ws1.receive_text())
            two = json.loads(ws2.receive_text())
            assert one["service_item_id"] == sid
            assert two["service_item_id"] == sid
            assert one["ticket_id"] == join.json()["id"]
            assert two["ticket_id"] == join.json()["id"]
            assert one["status"] == "waiting"
            assert two["status"] == "waiting"
