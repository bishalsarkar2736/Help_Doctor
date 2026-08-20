"""`*.base` in ALLOWED_HOSTS: the one wildcard this deployment implements.

Tenant subdomains need the allowlist to cover hosts nobody enumerated in
advance. The danger in doing that is obvious — an allowlist that globs too
eagerly is not an allowlist — so the wildcard is deliberately narrow, and most
of what follows asserts what it does NOT admit.
"""

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.try_except.trusted_host_middleware import _host_is_served

BASE = "example.com"

_REQUIRED = dict(
    POSTGRES_HOST="localhost",
    POSTGRES_DB="db",
    POSTGRES_USER="u",
    POSTGRES_PASSWORD="p",
    JWT_SECRET_KEY="x" * 40,
    BASE_URL="http://localhost:8000",
    GOOGLE_CLIENT_ID="id",
    GOOGLE_CLIENT_SECRET="secret",
    MAIL_HOST="localhost",
    MAIL_USERNAME="",
    MAIL_PASSWORD="",
    MAIL_FROM="noreply@example.com",
    BKASH_BASE_URL="https://example.com",
    BKASH_APP_KEY="k",
    BKASH_APP_SECRET="s",
    BKASH_USERNAME="u",
    BKASH_PASSWORD="p",
    BKASH_CALLBACK_URL="https://example.com/cb",
    NAGAD_BASE_URL="https://example.com",
    NAGAD_MERCHANT_ID="m",
    NAGAD_PUBLIC_KEY="k",
    NAGAD_PRIVATE_KEY="k",
    NAGAD_CALLBACK_URL="https://example.com/cb",
    ROCKET_BASE_URL="https://example.com",
    ROCKET_MERCHANT_ID="m",
    ROCKET_API_KEY="k",
    ROCKET_CALLBACK_URL="https://example.com/cb",
    WHATSAPP_ACCESS_TOKEN="t",
    WHATSAPP_PHONE_NUMBER_ID="1",
)


def _settings(**overrides) -> Settings:
    return Settings(_env_file=None, **{**_REQUIRED, **overrides})


def _served(host, allowed, env="development"):
    return _host_is_served(host, _settings(ALLOWED_HOSTS=allowed, ENV=env))


# ---------------------------------------------------------------------------
# Existing behaviour is untouched
# ---------------------------------------------------------------------------


def test_a_literal_host_is_still_served():
    assert _served("clinic.example.com", "clinic.example.com")


def test_loopback_is_still_served():
    assert _served("localhost", "clinic.example.com")
    assert _served("127.0.0.1", "clinic.example.com")


def test_an_unlisted_host_is_still_refused():
    assert not _served("evil.com", "clinic.example.com")


def test_a_config_with_no_wildcard_admits_nothing_extra():
    """The security posture without a wildcard is exactly what it was."""
    assert not _served(f"anything.{BASE}", f"clinic.{BASE}")


def test_wildcard_entries_are_not_in_the_literal_list():
    """"*.example.com" can never be a Host, so it must not sit in a list that
    is compared by equality."""
    settings = _settings(ALLOWED_HOSTS=f"{BASE},*.{BASE}")

    assert f"*.{BASE}" not in settings.allowed_hosts_list
    assert BASE in settings.allowed_hosts_list
    assert settings.allowed_host_suffixes == [BASE]


# ---------------------------------------------------------------------------
# What the wildcard admits
# ---------------------------------------------------------------------------


def test_a_tenant_host_is_served():
    assert _served(f"clinic-a.{BASE}", f"{BASE},*.{BASE}")


def test_the_port_is_ignored_as_before():
    assert _served(f"clinic-a.{BASE}:8000", f"{BASE},*.{BASE}")


def test_the_apex_needs_its_own_entry():
    """A wildcard covers subdomains, not the domain itself — so a config that
    forgets the apex does not accidentally serve it."""
    assert not _served(BASE, f"*.{BASE}")
    assert _served(BASE, f"{BASE},*.{BASE}")


# ---------------------------------------------------------------------------
# What it refuses
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "host",
    [
        f"a.b.{BASE}",                 # nested: more than one label
        "clinic-a.evil.com",           # foreign domain
        f"{BASE}.evil.com",            # base as a prefix of someone else's
        f"evil-{BASE}",                # base as a suffix without the dot
        f"x{BASE}",                    # no separating dot
        f"-bad.{BASE}",                # malformed label
        f"bad-.{BASE}",                # malformed label
        f"under_score.{BASE}",         # not a DNS label character
        f".{BASE}",                    # empty label
        "127.0.0.2",                   # unrelated address
    ],
)
def test_hosts_the_wildcard_does_not_admit(host):
    assert not _served(host, f"{BASE},*.{BASE}")


@pytest.mark.parametrize("label", ["api", "www", "grafana", "mail", "admin"])
def test_reserved_labels_are_refused_even_under_the_wildcard(label):
    """The allowlist inherits the reserved list from the tenant rule, so a host
    the platform intends to use for itself cannot be claimed."""
    assert not _served(f"{label}.{BASE}", f"{BASE},*.{BASE}")


# ---------------------------------------------------------------------------
# Malformed wildcard configuration is refused at startup, in production
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "allowed",
    [
        "*",                       # reads like "disable the check"
        f"**.{BASE}",              # two stars
        f"foo.*.{BASE}",           # star in the middle
        f"*.*.{BASE}",             # two wildcards
        f"clinic.*.{BASE}",
        "*.localhost",             # single-label base
        "*.",                      # no base at all
    ],
)
def test_malformed_wildcards_are_refused_in_production(allowed):
    with pytest.raises(ValidationError):
        _settings(ENV="production", ALLOWED_HOSTS=f"{BASE},{allowed}")


def test_a_well_formed_wildcard_is_accepted_in_production():
    settings = _settings(ENV="production", ALLOWED_HOSTS=f"{BASE},*.{BASE}")

    assert settings.allowed_host_suffixes == [BASE]


def test_production_still_refuses_test_hostnames():
    """Adding wildcard support must not have loosened the other rules."""
    with pytest.raises(ValidationError):
        _settings(ENV="production", ALLOWED_HOSTS=f"{BASE},testserver")


def test_production_still_refuses_loopback_only():
    with pytest.raises(ValidationError):
        _settings(ENV="production", ALLOWED_HOSTS="localhost,127.0.0.1")


def test_a_wildcard_alone_satisfies_the_non_loopback_requirement():
    settings = _settings(ENV="production", ALLOWED_HOSTS=f"*.{BASE}")

    assert settings.allowed_host_suffixes == [BASE]
