"""Log-only SMS gateway for local development and CI.

This is what ``SMS_DELIVERY_STUB_ENABLED`` used to do inline in
``SmsNotifier``, lifted behind the :class:`SmsProvider` port. Selecting
it exercises the *entire* real path — preference resolution, E.164
normalisation, body rendering, segment accounting, ledger write — and
stops only at the network boundary. That makes it a much better local
default than the old flag, which short-circuited before any of it.
"""

from __future__ import annotations

import logging
import uuid

from werefa.notifications.infrastructure.sms.base import (
    SmsMessage,
    SmsResult,
)
from werefa.notifications.infrastructure.sms.rendering import segment_count

logger = logging.getLogger(__name__)


class ConsoleSmsProvider:
    name = "console"

    @property
    def configured(self) -> bool:
        return True

    def send(self, message: SmsMessage) -> SmsResult:
        message_id = f"console-{uuid.uuid4()}"
        # Deliberately logs the recipient and body unmasked, unlike the real
        # adapters: seeing the exact text that would have been sent is the
        # entire point of this gateway. Do not select it outside dev/CI.
        logger.info(
            "sms_console_delivered",
            extra={
                "provider": self.name,
                "to": message.to,
                "body": message.body,
                "segments": segment_count(message.body),
                "provider_message_id": message_id,
            },
        )
        return SmsResult.sent(provider=self.name, provider_message_id=message_id)
