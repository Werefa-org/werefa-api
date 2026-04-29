import uuid
from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, field_serializer

from werefa.shared.models import utcnow

BROADCAST_EVENT_TYPE = "broadcast_v1"


class QueueEventType(StrEnum):
    """Payload `type` field for v1 events."""

    queue_updated = "queue_updated"


class QueueEventV1(BaseModel):
    """
    Wire format for queue notifications (extend with `data` in later versions if needed).
    """

    v: int = 1
    type: str = Field(default=QueueEventType.queue_updated, min_length=1, max_length=64)
    service_item_id: uuid.UUID
    ticket_id: uuid.UUID | None = None
    status: str | None = Field(default=None, max_length=32)
    position: int | None = Field(default=None, ge=1)
    occurred_at: datetime
    reason: str | None = Field(
        default=None,
        max_length=64,
        description="Hint for clients: join, walk_in, call_next, status_update, ...",
    )

    @field_serializer("occurred_at")
    def _ser_time(self, v: datetime) -> str:
        return v.isoformat()

    @classmethod
    def build(
        cls,
        service_item_id: uuid.UUID,
        *,
        ticket_id: uuid.UUID | None,
        status: str | None,
        position: int | None,
        reason: str | None,
    ) -> "QueueEventV1":
        return cls(
            type=QueueEventType.queue_updated,
            service_item_id=service_item_id,
            ticket_id=ticket_id,
            status=status,
            position=position,
            occurred_at=utcnow(),
            reason=reason,
        )


class BroadcastEventV1(BaseModel):
    """Wire format for provider broadcasts (FR-08, UC-11).

    Note the ``type`` is a fixed string (``broadcast_v1``) so clients can
    discriminate between queue updates and broadcasts on the same socket
    without parsing the full payload twice.
    """

    v: int = 1
    type: Literal["broadcast_v1"] = "broadcast_v1"
    broadcast_id: uuid.UUID
    provider_id: uuid.UUID
    # ``None`` means the message was published to every active service
    # line of the provider; the realtime layer fans it out on each line's
    # channel, so subscribers always see a concrete service line they're
    # already attached to.
    service_item_id: uuid.UUID | None = None
    body: str = Field(min_length=1, max_length=500)
    severity: Literal["info", "warning", "critical"] = "info"
    occurred_at: datetime

    @field_serializer("occurred_at")
    def _ser_time(self, v: datetime) -> str:
        return v.isoformat()
