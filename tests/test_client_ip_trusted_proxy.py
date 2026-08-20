"""Which address a request is rate-limited against.

The whole point is that X-Forwarded-For is written by whoever connected. Behind
a proxy that overwrites it, it is the only way to see the real client; reached
directly, it is a field the caller fills in themselves. Believing it in the
second case lets anyone mint a fresh rate-limit budget per request, so most of
these tests are about NOT believing it.
"""

import pytest
from pydantic import ValidationError

from app.config import Settings, get_settings
from app.core.limiter import authenticated_key
from app.utils.request_ip import client_ip_from

PROXY_NET = "172.18.0.0/16"
PROXY_IP = "172.18.0.5"
CLIENT = "203.0.113.7"
OTHER_CLIENT = "198.51.100.9"


class _Request:
    """The two things client_ip_from reads."""

    def __init__(self, peer, forwarded=None, authorization=None):
        self.client = type("C", (), {"host": peer})() if peer else None
        self.headers = {}
        if forwarded is not None:
            self.headers["x-forwarded-for"] = forwarded
        if authorization is not None:
            self.headers["Authorization"] = authorization


@pytest.fixture
def trusted(monkeypatch):
    monkeypatch.setattr(get_settings(), "TRUSTED_PROXY_IPS", PROXY_NET, raising=False)
    yield


@pytest.fixture
def untrusted(monkeypatch):
    monkeypatch.setattr(get_settings(), "TRUSTED_PROXY_IPS", "", raising=False)
    yield


# ---------------------------------------------------------------------------
# Direct requests
# ---------------------------------------------------------------------------


def test_a_direct_request_uses_the_peer_address(untrusted):
    assert client_ip_from(_Request(CLIENT)) == CLIENT


def test_a_request_with_no_client_is_not_an_error(untrusted):
    assert client_ip_from(_Request(None)) == "unknown"


# ---------------------------------------------------------------------------
# Behind a trusted proxy
# ---------------------------------------------------------------------------


def test_a_trusted_proxy_reveals_the_real_client(trusted):
    request = _Request(PROXY_IP, forwarded=CLIENT)

    assert client_ip_from(request) == CLIENT


def test_the_proxys_own_hops_are_skipped(trusted):
    """nginx appends with $proxy_add_x_forwarded_for, so the chain can end in
    addresses that are themselves proxies."""
    request = _Request(PROXY_IP, forwarded=f"{CLIENT}, 172.18.0.9")

    assert client_ip_from(request) == CLIENT


def test_two_clients_behind_one_proxy_get_separate_identities(trusted):
    """The defect this fixes: both would otherwise be the proxy's address and
    share a single bucket."""
    first = client_ip_from(_Request(PROXY_IP, forwarded=CLIENT))
    second = client_ip_from(_Request(PROXY_IP, forwarded=OTHER_CLIENT))

    assert first != second
    assert {first, second} == {CLIENT, OTHER_CLIENT}


# ---------------------------------------------------------------------------
# Spoofing
# ---------------------------------------------------------------------------


def test_an_untrusted_peer_cannot_forge_its_address(untrusted):
    """Reaching the API directly and claiming to be someone else changes
    nothing — the peer address is what counts."""
    request = _Request(CLIENT, forwarded="1.2.3.4")

    assert client_ip_from(request) == CLIENT


def test_an_untrusted_peer_cannot_forge_even_when_a_proxy_is_configured(trusted):
    request = _Request(CLIENT, forwarded="1.2.3.4")

    assert client_ip_from(request) == CLIENT


def test_a_client_cannot_prepend_a_fake_hop_through_a_trusted_proxy(trusted):
    """The client controls the LEFT of the chain: it can send its own
    X-Forwarded-For and the proxy appends to it. Reading from the right is what
    makes that harmless."""
    request = _Request(PROXY_IP, forwarded=f"1.2.3.4, {CLIENT}")

    assert client_ip_from(request) == CLIENT


def test_malformed_forwarded_entries_do_not_become_buckets(trusted):
    """"not-an-ip" would otherwise be a rate-limit identity of its own, and a
    fresh one for every variation."""
    request = _Request(PROXY_IP, forwarded=f"junk, not-an-ip, {CLIENT}")

    assert client_ip_from(request) == CLIENT


def test_an_entirely_malformed_chain_falls_back_to_the_peer(trusted):
    request = _Request(PROXY_IP, forwarded="junk, ,not-an-ip")

    assert client_ip_from(request) == PROXY_IP


def test_an_empty_forwarded_header_falls_back_to_the_peer(trusted):
    assert client_ip_from(_Request(PROXY_IP, forwarded="")) == PROXY_IP


# ---------------------------------------------------------------------------
# The limiter uses it
# ---------------------------------------------------------------------------


def test_the_limiter_key_function_is_the_shared_helper():
    from app.core.limiter import limiter

    assert limiter._key_func is client_ip_from


def test_the_authenticated_key_falls_back_to_the_real_client(trusted):
    """No token, so it falls through to the address — which must be the client,
    not the proxy."""
    request = _Request(PROXY_IP, forwarded=CLIENT)

    assert authenticated_key(request) == CLIENT


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


def _settings(**overrides):
    base = dict(
        POSTGRES_HOST="localhost", POSTGRES_DB="db", POSTGRES_USER="u",
        POSTGRES_PASSWORD="p", JWT_SECRET_KEY="x" * 40,
        BASE_URL="http://localhost:8000", GOOGLE_CLIENT_ID="id",
        GOOGLE_CLIENT_SECRET="s", MAIL_HOST="localhost", MAIL_USERNAME="",
        MAIL_PASSWORD="", MAIL_FROM="a@example.com",
        BKASH_BASE_URL="https://e.com", BKASH_APP_KEY="k", BKASH_APP_SECRET="s",
        BKASH_USERNAME="u", BKASH_PASSWORD="p", BKASH_CALLBACK_URL="https://e.com/c",
        NAGAD_BASE_URL="https://e.com", NAGAD_MERCHANT_ID="m", NAGAD_PUBLIC_KEY="k",
        NAGAD_PRIVATE_KEY="k", NAGAD_CALLBACK_URL="https://e.com/c",
        ROCKET_BASE_URL="https://e.com", ROCKET_MERCHANT_ID="m", ROCKET_API_KEY="k",
        ROCKET_CALLBACK_URL="https://e.com/c", WHATSAPP_ACCESS_TOKEN="t",
        WHATSAPP_PHONE_NUMBER_ID="1",
    )
    return Settings(_env_file=None, **{**base, **overrides})


def test_the_default_trusts_no_proxy():
    assert _settings().trusted_proxy_networks == ()


def test_a_star_is_refused():
    """--forwarded-allow-ips=* by another name."""
    with pytest.raises(ValidationError):
        _settings(TRUSTED_PROXY_IPS="*")


def test_a_malformed_entry_is_refused_at_startup():
    with pytest.raises(ValidationError):
        _settings(TRUSTED_PROXY_IPS="not-a-network")


def test_a_bare_address_is_accepted_as_a_single_host():
    networks = _settings(TRUSTED_PROXY_IPS=PROXY_IP).trusted_proxy_networks

    assert len(networks) == 1
    assert networks[0].prefixlen == 32
