"""Provider-agnostic SMS delivery for the ``sms`` notification channel."""

from werefa.notifications.infrastructure.sms.base import (
    DisabledSmsProvider,
    SmsMessage,
    SmsOutcome,
    SmsProvider,
    SmsResult,
)
from werefa.notifications.infrastructure.sms.console import ConsoleSmsProvider
from werefa.notifications.infrastructure.sms.factory import (
    build_sms_provider,
    get_sms_provider,
    known_sms_providers,
    register_sms_provider,
    set_sms_provider,
)
from werefa.notifications.infrastructure.sms.phone import to_e164
from werefa.notifications.infrastructure.sms.rendering import (
    render_sms_body,
    segment_count,
)
from werefa.notifications.infrastructure.sms.twilio import (
    RECEIPT_REFERENCE_PARAM,
    TwilioSmsProvider,
    classify_status,
    validate_signature,
)

__all__ = [
    "RECEIPT_REFERENCE_PARAM",
    "ConsoleSmsProvider",
    "DisabledSmsProvider",
    "SmsMessage",
    "SmsOutcome",
    "SmsProvider",
    "SmsResult",
    "TwilioSmsProvider",
    "build_sms_provider",
    "classify_status",
    "get_sms_provider",
    "known_sms_providers",
    "register_sms_provider",
    "render_sms_body",
    "segment_count",
    "set_sms_provider",
    "to_e164",
    "validate_signature",
]
