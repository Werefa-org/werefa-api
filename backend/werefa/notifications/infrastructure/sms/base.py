"""The SMS port: what every gateway adapter must look like (FR-07).

``SmsNotifier`` talks to this protocol and never to a vendor SDK, so
swapping Twilio for an aggregator (Africa's Talking, Vonage, an MNO
bulk-SMS endpoint) means writing one new adapter and flipping
``SMS_PROVIDER`` — no changes in the dispatcher, the ledger, or tests
that don't specifically cover the vendor.

Adapters return an :class:`SmsResult` instead of raising. The three
outcomes are deliberately coarser than any vendor's error catalogue but
finer than the ``bool`` the ``Notifier`` protocol wants, because the
retry/escalation question ("is it worth trying again?") is the only
distinction the rest of the system needs:

``sent``
    The gateway accepted the message. Note this is *acceptance*, not
    handset delivery — carriers report that asynchronously, which is a
    webhook (see ``docs/missing.md``) not a return value.
``rejected``
    Permanent. Bad number, blocked recipient, unusable credentials.
    Retrying the same message will fail the same way.
``unavailable``
    Transient. Timeout, gateway 5xx, rate limit, no credentials
    configured. The same message might succeed later.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol, runtime_checkable


class SmsOutcome(str, Enum):
    sent = "sent"
    rejected = "rejected"
    unavailable = "unavailable"


@dataclass(frozen=True)
class SmsMessage:
    """One outbound text, already normalised and rendered."""

    to: str
    """Recipient in E.164 (``+251911234567``) — adapters may assume this."""

    body: str

    idempotency_key: str | None = None
    """Passed through by adapters whose API supports de-duplication.

    Twilio's Messages resource has no such parameter, so its adapter
    ignores this. Kept on the port so a gateway that *does* support it
    doesn't force a signature change.
    """


@dataclass(frozen=True)
class SmsResult:
    outcome: SmsOutcome
    provider: str
    provider_message_id: str | None = None
    error_code: str | None = None
    error_detail: str | None = None

    @property
    def accepted(self) -> bool:
        return self.outcome is SmsOutcome.sent

    @property
    def retryable(self) -> bool:
        return self.outcome is SmsOutcome.unavailable

    @classmethod
    def sent(
        cls, *, provider: str, provider_message_id: str | None = None
    ) -> SmsResult:
        return cls(
            outcome=SmsOutcome.sent,
            provider=provider,
            provider_message_id=provider_message_id,
        )

    @classmethod
    def rejected(
        cls,
        *,
        provider: str,
        error_code: str | None = None,
        error_detail: str | None = None,
    ) -> SmsResult:
        return cls(
            outcome=SmsOutcome.rejected,
            provider=provider,
            error_code=error_code,
            error_detail=error_detail,
        )

    @classmethod
    def unavailable(
        cls,
        *,
        provider: str,
        error_code: str | None = None,
        error_detail: str | None = None,
    ) -> SmsResult:
        return cls(
            outcome=SmsOutcome.unavailable,
            provider=provider,
            error_code=error_code,
            error_detail=error_detail,
        )


@runtime_checkable
class SmsProvider(Protocol):
    """One SMS gateway.

    ``send`` must not raise for network or vendor-level failures — map
    them onto :class:`SmsResult` so the notifier can log a reason and
    the dispatcher can fall through to the next channel.

    ``runtime_checkable`` so a conformance test can assert new adapters
    fit the port. The check is shallow (attribute presence, not
    signatures) — it's a smoke test, not a substitute for mypy.
    """

    name: str

    @property
    def configured(self) -> bool:
        """False when credentials are missing, so the notifier can skip
        the network round-trip entirely and let dispatch fall through."""
        ...

    def send(self, message: SmsMessage) -> SmsResult: ...


class DisabledSmsProvider:
    """Default when ``SMS_PROVIDER`` is unset — SMS is simply off.

    Reports ``unavailable`` rather than ``rejected``: nothing is wrong
    with the message, the deployment just hasn't turned SMS on.
    """

    name = "disabled"

    @property
    def configured(self) -> bool:
        return False

    def send(self, message: SmsMessage) -> SmsResult:
        return SmsResult.unavailable(
            provider=self.name, error_code="sms_disabled"
        )
