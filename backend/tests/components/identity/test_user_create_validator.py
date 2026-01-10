"""Pure-validation tests for `UserCreate` and the `user_type` invariants.

These tests are fast (no DB, no app) and document the contract of the model
so future refactors don't silently change semantics.
"""

import pytest
from pydantic import ValidationError

from werefa.shared.enums import UserType
from werefa.shared.models import UserCreate


def test_default_user_type_is_customer() -> None:
    user = UserCreate(email="customer@example.com", password="longpassword1")
    assert user.user_type == UserType.customer.value
    assert user.is_superuser is False


def test_explicit_provider_user_type_is_preserved() -> None:
    user = UserCreate(
        email="provider@example.com",
        password="longpassword1",
        user_type=UserType.provider.value,
    )
    assert user.user_type == UserType.provider.value


def test_superuser_forces_user_type_admin() -> None:
    user = UserCreate(
        email="admin@example.com",
        password="longpassword1",
        is_superuser=True,
    )
    assert user.user_type == UserType.admin.value


def test_superuser_with_explicit_customer_is_overridden_to_admin() -> None:
    """Convenience behaviour: keep `user_type` consistent with `is_superuser`."""
    user = UserCreate(
        email="admin@example.com",
        password="longpassword1",
        is_superuser=True,
        user_type=UserType.customer.value,
    )
    assert user.user_type == UserType.admin.value


def test_admin_user_type_without_superuser_is_rejected() -> None:
    """Setting `user_type='admin'` directly without `is_superuser=True` is invalid."""
    with pytest.raises(ValidationError):
        UserCreate(
            email="impersonator@example.com",
            password="longpassword1",
            user_type=UserType.admin.value,
        )
