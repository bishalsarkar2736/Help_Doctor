"""Rejecting a Host header this deployment does not serve.

The value is supplied by the client and nginx forwards it verbatim, so every
piece of code that trusts it — absolute URLs in emails, cache keys, and tenant
resolution once it arrives — inherits whatever a caller chose to send.
"""

import pytest

from app.config import Settings, get_settings


def _hosts(**overrides) -> Settings:
    """Settings with the host allowlist pinned, everything else as configured."""
    return Settings(**overrides)


# ---------------------------------------------------------------------------
# The allowlist
# ---------------------------------------------------------------------------


def test_loopback_is_always_allowed():
    """The container healthcheck calls localhost:8000, in every environment.

    Leaving this to configuration means one missing entry marks every container
    unhealthy and takes the deployment down.
    """
    settings = _hosts(ALLOWED_HOSTS="clinic.example.com")

    assert "localhost" in settings.allowed_hosts_list
    assert "127.0.0.1" in settings.allowed_hosts_list


def test_configured_hosts_are_allowed():
    settings = _hosts(ALLOWED_HOSTS="clinic.example.com, other.example.com")

    assert "clinic.example.com" in settings.allowed_hosts_list
    assert "other.example.com" in settings.allowed_hosts_list


def test_hosts_are_lowercased_and_trimmed():
    """Host comparison is case-insensitive; the allowlist must match that."""
    settings = _hosts(ALLOWED_HOSTS="  Clinic.Example.COM  ")

    assert "clinic.example.com" in settings.allowed_hosts_list


def test_the_list_has_no_duplicates():
    settings = _hosts(ALLOWED_HOSTS="localhost,localhost,clinic.example.com")

    assert len(settings.allowed_hosts_list) == len(set(settings.allowed_hosts_list))


def test_production_refuses_the_development_default():
    """Only loopback in production means nginx's forwarded Host is rejected.

    Every request would 400. Failing at startup says so before the containers
    are rolling.
    """
    with pytest.raises(ValueError, match="ALLOWED_HOSTS"):
        _hosts(
            ENV="production",
            # Pinned because the developer's own .env may enable it, and that
            # validator would fire first and mask what this test asserts.
            DEBUG=False,
            PAYMENT_GATEWAY="bkash",
            ALLOWED_HOSTS="localhost,127.0.0.1,testserver",
        )


def test_production_refuses_a_leaked_test_hostname():
    """A real hostname alongside the test one is the likelier mistake."""
    with pytest.raises(ValueError, match="test-only"):
        _hosts(
            ENV="production",
            DEBUG=False,
            PAYMENT_GATEWAY="bkash",
            ALLOWED_HOSTS="clinic.example.com,testserver",
        )


def test_production_accepts_a_real_hostname():
    settings = _hosts(
        ENV="production",
        DEBUG=False,
        PAYMENT_GATEWAY="bkash",
        ALLOWED_HOSTS="clinic.example.com",
    )

    assert "clinic.example.com" in settings.allowed_hosts_list


# ---------------------------------------------------------------------------
# Requests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_allowed_host_passes(client):
    """testserver is what the whole suite uses; it must keep working."""
    response = await client.get("/health")

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_a_forged_host_is_rejected(client):
    response = await client.get("/health", headers={"Host": "evil.example.com"})

    assert response.status_code == 400
    assert response.json()["error"]["type"] == "InvalidHost"


@pytest.mark.asyncio
async def test_the_rejection_uses_the_api_error_envelope(client):
    """Starlette's own middleware answers in plain text, which a client parsing
    {"error": {...}} would read as a transport failure rather than a refusal."""
    response = await client.get("/health", headers={"Host": "evil.example.com"})

    body = response.json()
    assert set(body["error"]) >= {"type", "message"}


@pytest.mark.asyncio
async def test_the_port_is_not_part_of_the_comparison(client):
    """The same host on :8000 and :443 is the same host."""
    response = await client.get("/health", headers={"Host": "testserver:8000"})

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_loopback_reaches_the_healthcheck_endpoint(client):
    """Guards the exact call docker-compose makes."""
    response = await client.get("/health/live", headers={"Host": "localhost:8000"})

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_x_forwarded_host_cannot_override(client):
    """nginx sets it from the same client value, so honouring it would add a
    second spoofable channel reaching the same decision."""
    response = await client.get(
        "/health",
        headers={"Host": "evil.example.com", "X-Forwarded-Host": "testserver"},
    )

    assert response.status_code == 400


@pytest.mark.asyncio
async def test_a_forged_host_is_rejected_before_authentication(client):
    """It runs first, so nothing downstream sees the request at all."""
    response = await client.get(
        "/users/me", headers={"Host": "evil.example.com"}
    )

    assert response.status_code == 400
    assert get_settings().ENV != "production"
