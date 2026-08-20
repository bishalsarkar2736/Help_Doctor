"""The subdomain as it crosses the API boundary.

The domain rule itself is covered in tests/domain/test_clinic_subdomain.py.
These tests assert the schemas wire it up: that the value is validated and
normalised on the way in, that it is readable on the way out, and — the one
that matters most — that the ordinary clinic update flow cannot touch it.
"""

import pytest
from pydantic import ValidationError

from app.schemas.clinic_schema import (
    ClinicCreate,
    ClinicResponse,
    ClinicSubdomainUpdate,
    ClinicUpdate,
)


# ---------------------------------------------------------------------------
# ClinicUpdate must not expose it
# ---------------------------------------------------------------------------


def test_clinic_update_has_no_subdomain_field():
    """ClinicUpdate assigns every field unconditionally in clinic_service, so a
    client omitting `subdomain` would delete the clinic's hostname and break
    every URL issued for it. The field must not exist on this schema."""
    assert "subdomain" not in ClinicUpdate.model_fields


def test_clinic_update_ignores_a_subdomain_that_is_sent_anyway():
    """Even a client that sends it must not be able to set it here."""
    payload = ClinicUpdate(name="City Care", subdomain="citycare")

    assert not hasattr(payload, "subdomain")


# ---------------------------------------------------------------------------
# ClinicCreate accepts and normalises it
# ---------------------------------------------------------------------------


def test_create_accepts_a_valid_subdomain():
    assert ClinicCreate(name="City Care", subdomain="citycare").subdomain == "citycare"


def test_create_without_a_subdomain_is_valid():
    """Most clinics are created before their DNS is decided."""
    assert ClinicCreate(name="City Care").subdomain is None


def test_create_normalises_case_and_whitespace():
    """DNS is case-insensitive; the unique index is not."""
    clinic = ClinicCreate(name="City Care", subdomain="  CityCare  ")

    assert clinic.subdomain == "citycare"


def test_create_turns_an_empty_subdomain_into_none():
    """Empty string would look configured while matching no request."""
    assert ClinicCreate(name="City Care", subdomain="   ").subdomain is None


@pytest.mark.parametrize(
    "value",
    ["-citycare", "citycare-", "city care", "city_care", "city.care", "a" * 64],
)
def test_create_rejects_malformed_subdomains(value):
    with pytest.raises(ValidationError):
        ClinicCreate(name="City Care", subdomain=value)


@pytest.mark.parametrize("value", ["api", "www", "grafana", "mail", "API"])
def test_create_rejects_reserved_subdomains(value):
    """Reserved names collide with infrastructure that already answers on them,
    and a tenant identity cannot be reclaimed once issued."""
    with pytest.raises(ValidationError):
        ClinicCreate(name="City Care", subdomain=value)


# ---------------------------------------------------------------------------
# The dedicated change schema
# ---------------------------------------------------------------------------


def test_subdomain_update_accepts_a_valid_value():
    assert ClinicSubdomainUpdate(subdomain="citycare").subdomain == "citycare"


def test_subdomain_update_requires_the_field():
    """No default, so clearing the subdomain is an explicit null rather than an
    accident of omission."""
    with pytest.raises(ValidationError):
        ClinicSubdomainUpdate()


def test_subdomain_update_allows_an_explicit_null_to_clear_it():
    assert ClinicSubdomainUpdate(subdomain=None).subdomain is None


def test_subdomain_update_applies_the_same_rule():
    with pytest.raises(ValidationError):
        ClinicSubdomainUpdate(subdomain="api")


# ---------------------------------------------------------------------------
# ClinicResponse
# ---------------------------------------------------------------------------


def test_response_exposes_the_subdomain():
    assert "subdomain" in ClinicResponse.model_fields


def test_response_defaults_to_none_for_a_clinic_without_one():
    response = ClinicResponse(
        id=1,
        name="City Care",
        logo_url=None,
        address=None,
        phone=None,
        email=None,
        website=None,
        primary_color=None,
    )

    assert response.subdomain is None
