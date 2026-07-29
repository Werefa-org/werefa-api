"""Selecting the SMS gateway by name.

``SMS_PROVIDER`` is a plain string rather than a ``Literal`` so a gateway
can be added without editing ``Settings``: write an adapter, call
:func:`register_sms_provider` at import time, set the env var. Unknown
names fail loudly at build time with the list of registered ones, which
is the diagnosis you actually want for a typo'd env var.

The built provider is cached module-level and swapped in tests through
:func:`set_sms_provider`, mirroring how ``notifications.application.
service`` handles its notifier registry.
"""

from __future__ import annotations

from collections.abc import Callable

from werefa.notifications.infrastructure.sms.base import (
    DisabledSmsProvider,
    SmsProvider,
)
from werefa.notifications.infrastructure.sms.console import ConsoleSmsProvider
from werefa.notifications.infrastructure.sms.twilio import TwilioSmsProvider

SmsProviderFactory = Callable[[], SmsProvider]

_FACTORIES: dict[str, SmsProviderFactory] = {
    "disabled": DisabledSmsProvider,
    "console": ConsoleSmsProvider,
    "twilio": TwilioSmsProvider.from_settings,
}

_provider: SmsProvider | None = None


def register_sms_provider(name: str, factory: SmsProviderFactory) -> None:
    """Add or replace a gateway under ``name``.

    Call before the first :func:`get_sms_provider` (import time is the
    natural place); the cache is not invalidated for you.
    """
    _FACTORIES[name.strip().lower()] = factory


def known_sms_providers() -> list[str]:
    return sorted(_FACTORIES)


def build_sms_provider(name: str | None = None) -> SmsProvider:
    """Instantiate the named gateway (default: ``settings.SMS_PROVIDER``)."""
    if name is None:
        from werefa.core.config import settings

        name = settings.SMS_PROVIDER
    key = (name or "disabled").strip().lower()
    factory = _FACTORIES.get(key)
    if factory is None:
        raise ValueError(
            f"Unknown SMS_PROVIDER {name!r}. "
            f"Registered providers: {', '.join(known_sms_providers())}"
        )
    return factory()


def get_sms_provider() -> SmsProvider:
    global _provider
    if _provider is None:
        _provider = build_sms_provider()
    return _provider


def set_sms_provider(provider: SmsProvider | None) -> None:
    """Test seam: install a fake gateway; pass ``None`` to reset."""
    global _provider
    _provider = provider
