"""Twilio adapter for the SMS port.

Talks to the Messages REST resource directly over ``httpx`` (already a
dependency) rather than pulling in ``twilio``: the surface we need is one
form-encoded POST with basic auth, and the SDK would add a second HTTP
stack plus its own exception hierarchy to translate back into
:class:`SmsResult` anyway.

Send is **synchronous and blocking**, and stays that way: it now runs on
the notification delivery worker
(``notifications/infrastructure/delivery.py``) rather than inside the
request, so blocking costs a worker thread instead of the caller — and,
on the one ``async def`` route that triggers alerts, instead of the event
loop. ``SMS_TIMEOUT_SECONDS`` therefore bounds how long one worker is
tied up before the attempt is called transient and retried, not how long
a customer waits for their ticket.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from werefa.notifications.infrastructure.sms.base import (
    SmsMessage,
    SmsResult,
)
from werefa.notifications.infrastructure.sms.phone import mask
from werefa.notifications.infrastructure.sms.rendering import segment_count

logger = logging.getLogger(__name__)

_API_VERSION = "2010-04-01"

# Twilio error codes that mean "try again later" even though the HTTP
# status alone would read as a permanent client error.
# https://www.twilio.com/docs/api/errors
_TRANSIENT_TWILIO_CODES = frozenset(
    {
        "20429",  # too many requests
        "31206",  # rate exceeded
        "63018",  # rate limit exceeded (channel)
    }
)


class TwilioSmsProvider:
    """Send via Twilio's Messages resource.

    Exactly one of ``from_number`` / ``messaging_service_sid`` is needed.
    A Messaging Service is preferable in production — it handles sender
    pools, sticky sender and per-country compliance — so it wins when
    both are configured.
    """

    name = "twilio"

    def __init__(
        self,
        *,
        account_sid: str | None,
        auth_token: str | None,
        from_number: str | None = None,
        messaging_service_sid: str | None = None,
        base_url: str = "https://api.twilio.com",
        timeout_seconds: float = 5.0,
        client: httpx.Client | None = None,
    ) -> None:
        self._account_sid = account_sid
        self._auth_token = auth_token
        self._from_number = from_number
        self._messaging_service_sid = messaging_service_sid
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._client = client

    @classmethod
    def from_settings(cls) -> TwilioSmsProvider:
        from werefa.core.config import settings

        return cls(
            account_sid=settings.TWILIO_ACCOUNT_SID,
            auth_token=settings.TWILIO_AUTH_TOKEN,
            from_number=settings.TWILIO_FROM_NUMBER,
            messaging_service_sid=settings.TWILIO_MESSAGING_SERVICE_SID,
            base_url=settings.TWILIO_API_BASE_URL,
            timeout_seconds=settings.SMS_TIMEOUT_SECONDS,
        )

    @property
    def configured(self) -> bool:
        return bool(
            self._account_sid
            and self._auth_token
            and (self._from_number or self._messaging_service_sid)
        )

    @property
    def _messages_url(self) -> str:
        return f"{self._base_url}/{_API_VERSION}/Accounts/{self._account_sid}/Messages.json"

    def _http(self) -> httpx.Client:
        if self._client is None:
            # Created on first send so importing this module never opens a
            # socket or reads TLS trust stores. The provider is cached for
            # the process lifetime, so this is one client per process —
            # exactly the lifetime httpx wants for connection reuse, which
            # is why there is no close() to call.
            self._client = httpx.Client(timeout=self._timeout_seconds)
        return self._client

    def _form_data(self, message: SmsMessage) -> dict[str, str]:
        data = {"To": message.to, "Body": message.body}
        if self._messaging_service_sid:
            data["MessagingServiceSid"] = self._messaging_service_sid
        else:
            # ``configured`` guarantees one of the two is set.
            data["From"] = self._from_number or ""
        return data

    def send(self, message: SmsMessage) -> SmsResult:
        if not self.configured:
            return SmsResult.unavailable(
                provider=self.name, error_code="twilio_not_configured"
            )

        try:
            response = self._http().post(
                self._messages_url,
                data=self._form_data(message),
                auth=(self._account_sid or "", self._auth_token or ""),
                timeout=self._timeout_seconds,
            )
        except httpx.TimeoutException as exc:
            logger.warning(
                "sms_twilio_timeout",
                extra={"provider": self.name, "to": mask(message.to)},
            )
            return SmsResult.unavailable(
                provider=self.name,
                error_code="timeout",
                error_detail=str(exc),
            )
        except httpx.HTTPError as exc:
            # Connection refused, DNS failure, TLS error, ... — all
            # infrastructure-level and worth retrying.
            logger.warning(
                "sms_twilio_transport_error",
                extra={"provider": self.name, "to": mask(message.to)},
            )
            return SmsResult.unavailable(
                provider=self.name,
                error_code="transport_error",
                error_detail=str(exc),
            )

        return self._interpret(response, message)

    def _interpret(
        self, response: httpx.Response, message: SmsMessage
    ) -> SmsResult:
        payload = _safe_json(response)

        if response.is_success:
            # Twilio can return 2xx with a terminal ``failed`` status when
            # it rejects the message before queueing it.
            status = str(payload.get("status") or "")
            if status == "failed":
                code = _stringify(payload.get("error_code"))
                return SmsResult.rejected(
                    provider=self.name,
                    error_code=code,
                    error_detail=_stringify(payload.get("error_message")),
                )
            sid = _stringify(payload.get("sid"))
            logger.info(
                "sms_twilio_accepted",
                extra={
                    "provider": self.name,
                    "to": mask(message.to),
                    "provider_message_id": sid,
                    "twilio_status": status,
                    "segments": segment_count(message.body),
                },
            )
            return SmsResult.sent(provider=self.name, provider_message_id=sid)

        code = _stringify(payload.get("code"))
        detail = _stringify(payload.get("message")) or response.text[:200]

        if (
            response.status_code == 429
            or response.status_code >= 500
            or (code is not None and code in _TRANSIENT_TWILIO_CODES)
        ):
            logger.warning(
                "sms_twilio_unavailable",
                extra={
                    "provider": self.name,
                    "status_code": response.status_code,
                    "twilio_code": code,
                },
            )
            return SmsResult.unavailable(
                provider=self.name, error_code=code, error_detail=detail
            )

        if response.status_code in (401, 403):
            # The message is fine; our credentials are not. Log loudly —
            # this is an ops problem that silent channel fall-through
            # would otherwise hide — and call it retryable so it isn't
            # recorded as the recipient's fault.
            logger.error(
                "sms_twilio_auth_failed",
                extra={
                    "provider": self.name,
                    "status_code": response.status_code,
                    "twilio_code": code,
                },
            )
            return SmsResult.unavailable(
                provider=self.name,
                error_code=code or "auth_failed",
                error_detail=detail,
            )

        logger.warning(
            "sms_twilio_rejected",
            extra={
                "provider": self.name,
                "status_code": response.status_code,
                "twilio_code": code,
                "to": mask(message.to),
            },
        )
        return SmsResult.rejected(
            provider=self.name, error_code=code, error_detail=detail
        )


def _safe_json(response: httpx.Response) -> dict[str, Any]:
    try:
        parsed = response.json()
    except ValueError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _stringify(value: Any) -> str | None:
    if value is None or value == "":
        return None
    return str(value)
