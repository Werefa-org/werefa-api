import uuid
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field, field_serializer

from werefa.shared.models import utcnow


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
    def build(cls, service_item_id: uuid.UUID, *, reason: str | None) -> "QueueEventV1":
        return cls(
            type=QueueEventType.queue_updated,
            service_item_id=service_item_id,
            occurred_at=utcnow(),
            reason=reason,
        )
