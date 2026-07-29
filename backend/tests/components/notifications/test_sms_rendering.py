"""SMS body composition and the segment cost that motivates it."""

from __future__ import annotations

from werefa.notifications.domain.triggers import decide_alert
from werefa.notifications.infrastructure.sms.rendering import (
    is_gsm_encodable,
    render_sms_body,
    segment_count,
    to_gsm_safe,
)


def test_typographic_punctuation_is_transliterated_to_gsm() -> None:
    text = to_gsm_safe("You’re next — head over…")
    assert text == "You're next - head over..."
    assert is_gsm_encodable(text)


def test_real_alert_halves_its_segment_cost_after_transliteration() -> None:
    """The em dash in our own trigger copy is the whole reason this exists.

    Asserted on the *rendered* message rather than the bare body, because
    that's what gets billed: brand prefix + copy + deep link runs past 70
    characters, so the UCS-2 encoding forced by one em dash costs two
    segments where GSM-7 costs one.
    """
    decision = decide_alert(position=1, last_alert_position=None, top_k=3)
    assert decision is not None
    link = "https://app.werefa.et/me/tickets/8f14e45f-ceea-467a-9b8a-1f2c3d4e5f60"

    untransliterated = f"Werefa: {decision.body} {link}"
    assert not is_gsm_encodable(untransliterated)
    assert segment_count(untransliterated) == 2

    rendered = render_sms_body(
        body=decision.body, brand="Werefa", ticket_link=link
    )
    assert is_gsm_encodable(rendered)
    assert segment_count(rendered) == 1


def test_every_trigger_body_becomes_gsm_encodable() -> None:
    bodies = [
        d.body
        for d in (
            decide_alert(position=1, last_alert_position=None, top_k=3),
            decide_alert(
                position=2, last_alert_position=None, top_k=3, has_serving_ahead=True
            ),
            decide_alert(position=3, last_alert_position=None, top_k=3),
        )
        if d is not None
    ]
    assert len(bodies) == 3
    for body in bodies:
        assert is_gsm_encodable(to_gsm_safe(body)), body


def test_non_latin_text_is_left_alone() -> None:
    # Amharic has no GSM equivalent; mangling it would be worse than
    # paying for UCS-2 segments.
    amharic = "ሰላም"
    assert to_gsm_safe(amharic) == amharic
    assert not is_gsm_encodable(amharic)


def test_segment_boundaries() -> None:
    assert segment_count("") == 0
    assert segment_count("a" * 160) == 1
    assert segment_count("a" * 161) == 2  # concatenation header costs 7 septets
    assert segment_count("a" * 306) == 2
    assert segment_count("a" * 307) == 3
    # UCS-2 once a non-GSM character appears.
    assert segment_count("ሰ" * 70) == 1
    assert segment_count("ሰ" * 71) == 2


def test_gsm_extended_characters_cost_two_septets() -> None:
    # "€" is in the extension table, so 80 of them exceed one segment.
    assert is_gsm_encodable("€" * 80)
    assert segment_count("€" * 80) == 1
    assert segment_count("€" * 81) == 2


def test_body_is_branded_and_carries_the_ticket_link() -> None:
    out = render_sms_body(
        body="You're next in line.",
        brand="Werefa",
        ticket_link="https://app.werefa.et/me/tickets/abc",
    )
    assert out == "Werefa: You're next in line. https://app.werefa.et/me/tickets/abc"


def test_brand_is_optional() -> None:
    assert render_sms_body(body="Queue closed.") == "Queue closed."


def test_long_body_is_truncated_to_the_cap() -> None:
    out = render_sms_body(body="x" * 500, brand="Werefa", max_chars=100)
    assert len(out) == 100
    assert out.endswith("...")
    assert out.startswith("Werefa: ")


def test_link_is_kept_whole_by_shortening_the_prose_instead() -> None:
    link = "https://app.werefa.et/me/tickets/abc"
    out = render_sms_body(
        body="y" * 300, brand="Werefa", ticket_link=link, max_chars=120
    )
    assert out.endswith(link)
    assert len(out) <= 120
    assert "..." in out


def test_link_is_dropped_when_it_would_leave_no_room_for_the_message() -> None:
    # A half-written URL costs the same to send and is useless, so the
    # message keeps its text and loses the link.
    link = "https://app.werefa.et/me/tickets/abcdefghijklmnopqrstuvwxyz"
    out = render_sms_body(
        body="z" * 200, brand="Werefa", ticket_link=link, max_chars=70
    )
    assert link not in out
    assert len(out) <= 70


def test_rendered_body_never_exceeds_the_cap() -> None:
    for length in (0, 1, 50, 159, 160, 161, 400):
        out = render_sms_body(
            body="q" * length,
            brand="Werefa",
            ticket_link="https://app.werefa.et/me/tickets/abc",
            max_chars=320,
        )
        assert len(out) <= 320
