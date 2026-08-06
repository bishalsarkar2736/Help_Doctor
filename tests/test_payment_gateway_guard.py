import pytest
from pydantic import ValidationError

from app.config import Settings, get_settings


def _base() -> dict:
    # Start from the loaded settings so every required field is present, then
    # override only what each case needs.
    data = get_settings().model_dump(mode="python")

    # A production Settings now has to name the hostnames it is served on, and
    # the development default carries the in-process test hostname. Pinned here
    # so these cases keep testing the payment guard rather than tripping over
    # an unrelated production rule.
    data["ALLOWED_HOSTS"] = "clinic.example.com"

    return data


def test_fake_gateway_blocked_in_production():
    data = {**_base(), "ENV": "production", "DEBUG": False, "PAYMENT_GATEWAY": "fake"}
    with pytest.raises(ValidationError, match="not allowed in production"):
        Settings(_env_file=None, **data)


def test_fake_gateway_allowed_in_development():
    data = {**_base(), "ENV": "development", "PAYMENT_GATEWAY": "fake"}
    settings = Settings(_env_file=None, **data)
    assert settings.PAYMENT_GATEWAY == "fake"


def test_bkash_gateway_allowed_in_production():
    data = {**_base(), "ENV": "production", "DEBUG": False, "PAYMENT_GATEWAY": "bkash"}
    settings = Settings(_env_file=None, **data)
    assert settings.PAYMENT_GATEWAY == "bkash"
