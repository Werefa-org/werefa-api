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

Delivery receipts
-----------------
The POST above answers one question — did Twilio *take* the message —
and for a long time we recorded that answer as "delivered". It is not:
Twilio queues first and finds out what the carrier thinks afterwards, so
a barred handset, a disconnected number and a text somebody acted on all
returned the same 201. Everything the customer's side of the story adds
comes back later on the ``StatusCallback`` URL.

So the send now asks for one, and this module owns both vendor-facing
halves of that conversation: :meth:`TwilioSmsProvider._status_callback`
builds the URL (carrying the ledger row id, which Twilio echoes back
verbatim), and :func:`validate_signature` / :func:`classify_status` read
the callback when it arrives. The route that receives it stays free of
Twilio specifics, exactly like the dispatcher is free of them on the way
out.

Callbacks are unauthenticated by nature — anybody who learns the URL can
POST to it — so :func:`validate_signature` is not optional decoration.
It is the only thing standing between a stranger and the ability to mark
a customer's alert delivered (or failed) at will.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
from typing import Any
from urllib.parse import urlencode, urlsplit, urlunsplit

import httpx

from werefa.notifications.domain.receipts import ReceiptOutcome
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

# Query parameter carrying our ledger row id on the status callback URL.
# Twilio calls the URL it was given, character for character, so anything
# we put here comes back — no vendor-side "client reference" field needed,
# and no lookup by message SID, which would race our own commit of it.
RECEIPT_REFERENCE_PARAM = "nid"

# https://www.twilio.com/docs/messaging/api/message-resource#message-status-values
#
# Only the terminal ones say anything. ``sent`` in particular is Twilio's
# word for "handed to the carrier", which is the exact optimism this
# module stopped recording as delivery — mapping it to ``delivered`` here
# would reintroduce the bug one layer further out.
_TWILIO_DELIVERED = frozenset({"delivered", "read"})
_TWILIO_FAILED = frozenset({"undelivered", "failed", "canceled", "cancelled"})
_TWILIO_IN_FLIGHT = frozenset(
    {"accepted", "scheduled", "queued", "sending", "sent", "receiving", "received"}
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
        status_callback_url: str | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self._account_sid = account_sid
        self._auth_token = auth_token
        self._from_number = from_number
        self._messaging_service_sid = messaging_service_sid
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._status_callback_url = (status_callback_url or "").strip() or None
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
            status_callback_url=settings.TWILIO_STATUS_CALLBACK_URL,
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

    def _status_callback(self, message: SmsMessage) -> str | None:
        """Where Twilio should report this message's fate, or ``None``.

        ``None`` on two counts, and both mean "do not ask": the
        deployment has not configured a reachable URL, or the send owns
        no ledger row for a receipt to update (the email-copy case, where
        SMS is not the channel being recorded).

        The row id rides in the query string because Twilio replays the
        URL exactly as given. The alternative — writing the message SID
        onto the row and having the webhook look it up — loses a race we
        cannot win: the first callback can arrive before the worker has
        committed the SID it would be looked up by.
        """
        if self._status_callback_url is None or message.receipt_reference is None:
            return None
        scheme, netloc, path, query, fragment = urlsplit(
            self._status_callback_url
        )
        # Appended rather than replacing: a deployment may already be
        # routing through a URL with query parameters of its own, and the
        # signature is computed over whatever we end up sending.
        extra = urlencode({RECEIPT_REFERENCE_PARAM: message.receipt_reference})
        query = f"{query}&{extra}" if query else extra
        return urlunsplit((scheme, netloc, path, query, fragment))

    def _form_data(self, message: SmsMessage) -> dict[str, str]:
        data = {"To": message.to, "Body": message.body}
        if self._messaging_service_sid:
            data["MessagingServiceSid"] = self._messaging_service_sid
        else:
            # ``configured`` guarantees one of the two is set.
            data["From"] = self._from_number or ""
        callback = self._status_callback(message)
        if callback is not None:
            data["StatusCallback"] = callback
        return data

    def send(self, message: SmsMessage) -> SmsResult:
        if not self.configured:
            return SmsResult.unavailable(
                provider=self.name, error_code="twilio_not_configured"
            )

        form = self._form_data(message)
        try:
            response = self._http().post(
                self._messages_url,
                data=form,
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

        return self._interpret(
            response, message, receipt_expected="StatusCallback" in form
        )

    def _interpret(
        self,
        response: httpx.Response,
        message: SmsMessage,
        *,
        receipt_expected: bool = False,
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
                    "receipt_expected": receipt_expected,
                },
            )
            # ``status`` here is ``queued``/``accepted`` — Twilio's own
            # word for "not delivered yet". Whether anyone hears about
            # what happens next depends entirely on whether we asked.
            return SmsResult.sent(
                provider=self.name,
                provider_message_id=sid,
                receipt_expected=receipt_expected,
            )

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


# --- the callback side -------------------------------------------------


def classify_status(raw_status: str | None) -> ReceiptOutcome:
    """Map a ``MessageStatus`` from a status callback onto the ledger's view.

    Unknown values — a status Twilio adds later, a typo in a replayed
    fixture — come back ``in_flight``, which is the do-nothing answer.
    Guessing ``failed`` would let an unrecognised word mark a customer
    unreachable, and guessing ``delivered`` would do the reverse; leaving
    the row alone is the only reading that cannot be wrong in a direction
    that matters.
    """
    value = (raw_status or "").strip().lower()
    if value in _TWILIO_DELIVERED:
        return ReceiptOutcome.delivered
    if value in _TWILIO_FAILED:
        return ReceiptOutcome.failed
    if value not in _TWILIO_IN_FLIGHT:
        logger.warning(
            "sms_twilio_unknown_callback_status",
            extra={"twilio_status": value or None},
        )
    return ReceiptOutcome.in_flight


def validate_signature(
    *,
    url: str,
    params: dict[str, str],
    signature: str | None,
    auth_token: str | None,
) -> bool:
    """Is this callback really from Twilio?

    Twilio's scheme (``X-Twilio-Signature``): take the full URL it was
    given — query string included — append every POST parameter as
    ``name`` immediately followed by ``value``, in order of parameter
    name, then HMAC-SHA1 the result with the account's auth token and
    base64 it.

    ``url`` must be the URL *we asked Twilio to call*, not the one the
    request appears to have arrived at. Behind a proxy or a load balancer
    those differ — scheme rewritten to http, host swapped for an internal
    name — and the difference is silent: every callback simply fails to
    verify and every receipt is dropped. The caller therefore rebuilds it
    from ``TWILIO_STATUS_CALLBACK_URL``.

    A missing signature or a missing token is ``False``. An endpoint that
    cannot check is an endpoint anybody can write the ledger through, and
    "we could not verify" must never be the same as "verified".
    """
    if not signature or not auth_token:
        return False
    payload = url + "".join(
        f"{key}{params[key]}" for key in sorted(params)
    )
    digest = hmac.new(
        auth_token.encode("utf-8"), payload.encode("utf-8"), hashlib.sha1
    ).digest()
    expected = base64.b64encode(digest).decode("ascii")
    # Constant-time: the comparison is against an attacker-supplied string,
    # and a short-circuiting one leaks the prefix a byte at a time.
    return hmac.compare_digest(expected, signature)


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
