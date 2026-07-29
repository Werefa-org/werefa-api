"""E.164 normalisation for free-form ``User.phone_number`` values.

Every case here is a shape that really turns up in the column: contact-card
paste, kiosk staff typing a local number, the ITU ``00`` prefix. The
important assertions are the *negative* ones — normalisation must refuse
rather than guess, because a wrong guess texts a stranger and still bills us.
"""

from __future__ import annotations

import pytest

from werefa.notifications.infrastructure.sms.phone import (
    mask,
    normalize_country_code,
    to_e164,
)

ET = "+251"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("+251911234567", "+251911234567"),
        ("+251 91 123 4567", "+251911234567"),
        ("+251-91-123-4567", "+251911234567"),
        ("(+251) 911.234.567", "+251911234567"),
        ("00251911234567", "+251911234567"),
        ("  +251911234567  ", "+251911234567"),
    ],
)
def test_already_international_numbers_normalise_without_a_default_country(
    raw: str, expected: str
) -> None:
    # No default country needed — the number already says where it lives.
    assert to_e164(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("0911234567", "+251911234567"),  # national trunk prefix
        ("0911 234 567", "+251911234567"),
        ("911234567", "+251911234567"),  # bare subscriber number
        ("251911234567", "+251911234567"),  # country code, no plus
    ],
)
def test_national_numbers_use_the_default_country_code(
    raw: str, expected: str
) -> None:
    assert to_e164(raw, default_country_code=ET) == expected


def test_default_country_code_accepts_both_plus_and_bare_forms() -> None:
    assert to_e164("0911234567", default_country_code="251") == to_e164(
        "0911234567", default_country_code="+251"
    )


def test_national_number_without_a_default_country_is_refused() -> None:
    # Guessing here would deliver a queue position to whoever owns that
    # number in whatever country we assumed.
    assert to_e164("0911234567") is None
    assert to_e164("911234567") is None


@pytest.mark.parametrize(
    "raw",
    [
        None,
        "",
        "   ",
        "not a phone",
        "+251-91-ABC-4567",
        "+25191",  # too short to be reachable
        "+2519112345678901234",  # more than 15 digits
        "0",
        "00",
        "+",
    ],
)
def test_unusable_values_are_refused(raw: str | None) -> None:
    assert to_e164(raw, default_country_code=ET) is None


@pytest.mark.parametrize("raw", ["+0911234567", "0000911234"])
def test_leading_zero_where_a_country_code_belongs_is_refused(raw: str) -> None:
    # A country code never starts with 0, so these are typos rather than
    # numbers. Stripping zeros until something looks plausible would
    # invent a recipient, so they are rejected outright.
    assert to_e164(raw, default_country_code=ET) is None


def test_double_zero_is_read_as_the_itu_prefix_not_a_trunk_typo() -> None:
    """``00`` wins over the national reading — documenting a real ambiguity.

    ``00911234567`` could be the ITU international prefix followed by
    country code 91, or a mistyped Ethiopian ``0911234567``. We take the
    first (standard) reading, so this is *not* normalised to +251.
    """
    assert to_e164("00911234567", default_country_code=ET) == "+911234567"


def test_only_one_trunk_zero_is_dropped_from_a_national_number() -> None:
    assert to_e164("0911234567", default_country_code=ET) == "+251911234567"


def test_short_country_code_does_not_truncate_a_matching_subscriber_number() -> None:
    """NANP regression: country code "1" is a common leading digit.

    ``1555000123`` is a 10-digit national number that merely starts with
    the country code. Believing the prefix would produce ``+1555000123``
    (10 digits) instead of ``+11555000123``.
    """
    # A genuine 11-digit NANP number keeps its shape.
    assert to_e164("14155550123", default_country_code="+1") == "+14155550123"
    # A 10-digit national number gets the code prepended.
    assert to_e164("4155550123", default_country_code="+1") == "+14155550123"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("+251", "251"),
        ("251", "251"),
        (" +1 ", "1"),
        (None, None),
        ("", None),
        ("+0251", None),  # country codes never start with 0
        ("+abcd", None),
        ("+1234", None),  # longer than any real country code
    ],
)
def test_country_code_parsing(raw: str | None, expected: str | None) -> None:
    assert normalize_country_code(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("+251911234567", "********4567"),  # 12 digits → 8 masked + last 4
        ("0911234567", "******4567"),
        ("1234", "****"),
        ("12", "**"),
        ("", "<none>"),
        (None, "<none>"),
    ],
)
def test_masking_keeps_only_the_last_four_digits(
    raw: str | None, expected: str
) -> None:
    assert mask(raw) == expected


def test_masking_never_leaks_the_country_or_operator_prefix() -> None:
    masked = mask("+251911234567")
    assert "251" not in masked
    assert masked.endswith("4567")


def test_result_is_always_within_the_phone_number_column_width() -> None:
    # User.phone_number is varchar(20); E.164 tops out at 16 chars with
    # the plus, so a normalised value always fits when written back.
    assert len(to_e164("+251911234567") or "") <= 20
