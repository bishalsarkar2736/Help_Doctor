import pytest
from pydantic import ValidationError

from app.schemas.user import UserCreate
from app.security.password_policy import validate_password_strength


def _make(pw: str):
    return UserCreate(email="a@b.com", full_name="Test User", password=pw, accepted_terms_version="2026-08-01", accepted_privacy_version="2026-08-01")


def test_accepts_strong_password():
    assert _make("secret123").password == "secret123"


@pytest.mark.parametrize(
    "pw",
    [
        "short1",       # too short
        "allletters",   # no digit
        "12345678",     # no letter
    ],
)
def test_rejects_weak_passwords(pw):
    with pytest.raises(ValidationError):
        _make(pw)


def test_rejects_over_max_length():
    with pytest.raises(ValidationError):
        _make("a1" + "x" * 100)


def test_validator_returns_value_unchanged():
    assert validate_password_strength("Passw0rd") == "Passw0rd"
