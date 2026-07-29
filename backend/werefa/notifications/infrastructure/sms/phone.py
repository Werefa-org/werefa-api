"""E.164 normalisation for ``User.phone_number``.

The column is free-form ``str | None`` (max 20 chars) filled in by users
and by kiosk staff, so by the time a number reaches a gateway it can look
like ``0911 234 567``, ``+251-91-123-4567`` or ``00251911234567``. Every
gateway worth using wants E.164, and most bill you for a rejected
message, so normalisation happens once here and adapters may assume
their input is already valid.

This is deliberately *not* a libphonenumber replacement — it does no
carrier or number-range validation, only shape normalisation. Numbers it
cannot confidently normalise come back as ``None``, which the notifier
treats as "this channel can't deliver" so dispatch falls through rather
than burning a paid send on a guess.
"""

from __future__ import annotations

# Users paste numbers from contact cards, so tolerate the usual grouping
# characters (including the non-breaking and narrow spaces that come out
# of iOS/Android contact pickers).
_SEPARATORS = " \t-()./  "

# E.164 allows at most 15 digits including the country code. The lower
# bound is a sanity floor: no reachable international number is shorter
# than 8 digits, and anything below that is almost always a truncated
# entry or an internal extension.
_MIN_DIGITS = 8
_MAX_DIGITS = 15


def _strip_separators(raw: str) -> str:
    return "".join(ch for ch in raw if ch not in _SEPARATORS)


def _valid(digits: str) -> str | None:
    if not digits.isdigit():
        return None
    if not _MIN_DIGITS <= len(digits) <= _MAX_DIGITS:
        return None
    if digits.startswith("0"):
        # A country code never starts with 0; this means a trunk prefix
        # survived, i.e. we failed to work out the country.
        return None
    return f"+{digits}"


def mask(number: str | None) -> str:
    """Redact a number for logging, keeping only the last 4 digits.

    Delivery logs are high-volume and long-lived, and a phone number is
    personal data on its own. The suffix is enough to correlate a
    complaint with a log line; the rest is not needed to operate this.
    """
    if not number:
        return "<none>"
    digits = [ch for ch in number if ch.isdigit()]
    if len(digits) <= 4:
        return "*" * len(digits)
    return "*" * (len(digits) - 4) + "".join(digits[-4:])


def normalize_country_code(raw: str | None) -> str | None:
    """Accept ``+251``/``251`` and return the bare digits, or ``None``."""
    if raw is None:
        return None
    code = _strip_separators(raw).lstrip("+")
    if not code.isdigit() or not 1 <= len(code) <= 3 or code.startswith("0"):
        return None
    return code


def to_e164(raw: str | None, *, default_country_code: str | None = None) -> str | None:
    """Best-effort E.164, or ``None`` when the input can't be trusted.

    ``default_country_code`` (``"+251"`` or ``"251"``) is what national
    numbers are assumed to belong to. Without it, only numbers that are
    already international (``+…`` or ``00…``) can be normalised.
    """
    if raw is None:
        return None
    cleaned = _strip_separators(raw)
    if not cleaned:
        return None

    if cleaned.startswith("+"):
        return _valid(cleaned[1:])

    # ``00`` is the ITU international prefix used across Europe and much
    # of Africa; treat it exactly like ``+``.
    if cleaned.startswith("00"):
        return _valid(cleaned[2:])

    if not cleaned.isdigit():
        return None

    country_code = normalize_country_code(default_country_code)
    if country_code is None:
        # Purely national digits with no country to attach them to. Guessing
        # would send someone else's phone a stranger's queue position.
        return None

    if cleaned.startswith("0"):
        # Single leading zero is the national trunk prefix (0911… → +251911…).
        # Only one is dropped; a second zero means the input is malformed and
        # ``_valid`` will reject it.
        return _valid(country_code + cleaned[1:])

    if cleaned.startswith(country_code):
        # Already carries the country code, just without ``+`` — but only
        # believe that if the result is a plausible length. Otherwise a
        # subscriber number that happens to begin with the same digits
        # (common where the code is short, e.g. NANP "1") would be
        # silently truncated.
        candidate = _valid(cleaned)
        if candidate is not None:
            return candidate

    return _valid(country_code + cleaned)
