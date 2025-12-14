import pytest

from werefa.providers.domain.membership_rules import (
    validate_remove_last_owner,
)


def test_cannot_remove_last_owner() -> None:
    with pytest.raises(ValueError, match="at least one owner"):
        validate_remove_last_owner(member_role="owner", owner_count=1)


def test_can_remove_owner_when_multiple() -> None:
    validate_remove_last_owner(member_role="owner", owner_count=2)


def test_non_owner_ok_with_single_owner() -> None:
    validate_remove_last_owner(member_role="staff", owner_count=1)
