"""Turning a notification into text that is cheap to send.

Unlike email, SMS is billed per *segment* and the segment size depends on
the alphabet: 160 characters if every character is in the GSM 03.38 set,
70 if even one isn't. The queue alert bodies in
``notifications/domain/triggers.py`` are written for humans and contain
typographic punctuation ("You're next — please head to the counter"),
and that single em dash is enough to halve the segment size and double
the bill for every alert we send.

So this module does two things before handing text to a gateway:
transliterate the handful of characters that have obvious GSM-safe
equivalents, then hard-cap the length. Characters with no equivalent
(Amharic, for instance) are left alone — those messages genuinely need
the wider alphabet and should be sent as UCS-2, not mangled.

Pure functions over primitives: no settings, no payload types, no
imports from the notifier. That keeps ``sms`` free of a cycle back into
the module that consumes it, and makes the cost rules testable on their
own.
"""

from __future__ import annotations

# Characters our own copy uses (or that arrive via line-chat previews)
# that are not in GSM 03.38 but have a faithful ASCII equivalent.
_GSM_SUBSTITUTIONS = {
    "—": "-",  # em dash
    "–": "-",  # en dash
    "‘": "'",  # left single quote
    "’": "'",  # right single quote / apostrophe
    "“": '"',  # left double quote
    "”": '"',  # right double quote
    "…": "...",  # horizontal ellipsis
    " ": " ",  # non-breaking space
    " ": " ",  # narrow no-break space
    "•": "*",  # bullet
    "→": "->",  # rightwards arrow
}

# GSM 03.38 basic character set — one septet each.
_GSM_BASIC = set(
    "@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞÆæßÉ !\"#¤%&'()*+,-./0123456789:;<=>?¡"
    "ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ§¿abcdefghijklmnopqrstuvwxyzäöñüà"
)

# Basic-set extensions — sent as an escape pair, so they cost two septets.
_GSM_EXTENDED = set("^{}\\[~]|€")

_GSM_SINGLE_SEGMENT = 160
_GSM_MULTI_SEGMENT = 153  # 7 septets go to the concatenation header
_UCS2_SINGLE_SEGMENT = 70
_UCS2_MULTI_SEGMENT = 67


def to_gsm_safe(text: str) -> str:
    """Replace typographic characters that would force UCS-2 encoding."""
    for char, replacement in _GSM_SUBSTITUTIONS.items():
        if char in text:
            text = text.replace(char, replacement)
    return text


def is_gsm_encodable(text: str) -> bool:
    return all(ch in _GSM_BASIC or ch in _GSM_EXTENDED for ch in text)


def segment_count(text: str) -> int:
    """How many SMS segments ``text`` will be billed as.

    Used for log lines rather than for any control flow — it makes an
    unexpectedly expensive template visible in production before it
    shows up on an invoice.
    """
    if not text:
        return 0
    if is_gsm_encodable(text):
        length = sum(2 if ch in _GSM_EXTENDED else 1 for ch in text)
        single, multi = _GSM_SINGLE_SEGMENT, _GSM_MULTI_SEGMENT
    else:
        # Characters outside the BMP take two UTF-16 code units.
        length = sum(2 if ord(ch) > 0xFFFF else 1 for ch in text)
        single, multi = _UCS2_SINGLE_SEGMENT, _UCS2_MULTI_SEGMENT
    if length <= single:
        return 1
    return -(-length // multi)  # ceiling division


def _truncate(text: str, limit: int) -> str:
    if limit <= 0 or len(text) <= limit:
        return text
    if limit <= 3:
        return text[:limit]
    return text[: limit - 3].rstrip() + "..."


def render_sms_body(
    *,
    body: str,
    brand: str | None = None,
    ticket_link: str | None = None,
    max_chars: int = 320,
) -> str:
    """Compose the text for one alert.

    Layout is ``"<brand>: <body> <link>"``. The link is dropped rather
    than truncated when it would not fit whole — a half-written URL costs
    the same as a whole one and is useless to the recipient.
    """
    text = to_gsm_safe(body).strip()
    if brand:
        text = f"{to_gsm_safe(brand).strip()}: {text}"

    if ticket_link:
        link = ticket_link.strip()
        candidate = f"{text} {link}"
        if len(candidate) <= max_chars:
            return candidate
        # Make room for the link by shortening the prose instead.
        room = max_chars - len(link) - 1
        if room >= 40:
            return f"{_truncate(text, room)} {link}"

    return _truncate(text, max_chars)
