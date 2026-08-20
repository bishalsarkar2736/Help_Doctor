"""The rule for what may become a tenant's hostname.

These are pure-function tests on purpose: the rule has to hold before any
routing exists, and it is the piece that cannot be corrected after the fact —
a subdomain that has been handed out is in URLs, emails and bookmarks.
"""

import pytest

from app.domain.clinics.subdomain import (
    MAX_LENGTH,
    RESERVED,
    InvalidSubdomain,
    normalize_subdomain,
    validate_subdomain,
)


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------


def test_the_value_is_lowercased():
    """DNS is case-insensitive; a unique index is not."""
    assert validate_subdomain("CityCare") == "citycare"


def test_surrounding_whitespace_is_removed():
    assert validate_subdomain("  citycare  ") == "citycare"


@pytest.mark.parametrize("value", ["", "   ", None])
def test_an_absent_subdomain_becomes_none_not_empty_string(value):
    """Empty string would look configured while matching no request — and two
    clinics storing it would collide on the unique index."""
    assert normalize_subdomain(value) is None
    assert validate_subdomain(value) is None


# ---------------------------------------------------------------------------
# RFC 1123 label
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    ["citycare", "city-care", "clinic1", "a", "1clinic", "a-b-c-1"],
)
def test_valid_labels_are_accepted(value):
    assert validate_subdomain(value) == value


@pytest.mark.parametrize(
    "value",
    [
        "-citycare",      # leading hyphen
        "citycare-",      # trailing hyphen
        "city care",      # space
        "city_care",      # underscore is not a DNS label character
        "city.care",      # a dot is a label separator, not part of one
        "city@care",
        "citycare!",
        "café",           # non-ASCII; punycode is not handled here
    ],
)
def test_malformed_labels_are_refused(value):
    with pytest.raises(InvalidSubdomain):
        validate_subdomain(value)


def test_a_label_at_the_dns_limit_is_accepted():
    assert validate_subdomain("a" * MAX_LENGTH) == "a" * MAX_LENGTH


def test_a_label_over_the_dns_limit_is_refused():
    """64 characters cannot be resolved, so it must not reach the database."""
    with pytest.raises(InvalidSubdomain):
        validate_subdomain("a" * (MAX_LENGTH + 1))


# ---------------------------------------------------------------------------
# Reserved names
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("value", ["api", "www", "grafana", "mail", "admin"])
def test_reserved_names_are_refused(value):
    with pytest.raises(InvalidSubdomain):
        validate_subdomain(value)


def test_reserved_names_are_refused_regardless_of_case():
    """The check runs after normalisation, or 'API' would slip through."""
    with pytest.raises(InvalidSubdomain):
        validate_subdomain("API")


def test_the_infrastructure_hostnames_this_stack_uses_are_reserved():
    """Each of these already answers on the compose network. A tenant holding
    one would collide with a service rather than merely look odd."""
    for name in ("api", "grafana", "prometheus", "minio", "jaeger"):
        assert name in RESERVED


def test_mail_hostnames_are_reserved():
    """A tenant holding one of these can break or intercept mail for the
    whole domain, which is not recoverable by renaming the tenant."""
    for name in ("mail", "smtp", "mx", "autodiscover"):
        assert name in RESERVED


def test_a_reserved_name_as_a_substring_is_still_allowed():
    """The reservation is on the whole label, not on the word appearing in it —
    'apiary-clinic' collides with nothing."""
    assert validate_subdomain("apiary-clinic") == "apiary-clinic"
