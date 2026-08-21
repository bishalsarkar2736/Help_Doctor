"""Which address a consent record names.

UserConsent.ip_address is evidence of who accepted the legal documents, so the
value has to be the caller's and not something the caller chose. This function
previously read X-Forwarded-For from whoever connected and took the LAST entry —
correct with exactly one trusted proxy appending to the chain, and wrong with
any other number. Putting a TLS terminator in front of nginx makes it two.
"""

import pytest

from app.config import get_settings
from app.services.consent_service import _client_ip

PROXY_NET = "172.18.0.0/16"
PROXY_IP = "172.18.0.5"
EDGE_IP = "172.18.0.9"
CLIENT = "203.0.113.7"


class _Request:
    def __init__(self, peer, forwarded=None):
        self.client = type("C", (), {"host": peer})() if peer else None
        self.headers = {}
        if forwarded is not None:
            self.headers["x-forwarded-for"] = forwarded


@pytest.fixture
def trusted(monkeypatch):
    monkeypatch.setattr(get_settings(), "TRUSTED_PROXY_IPS", PROXY_NET, raising=False)
    yield


@pytest.fixture
def untrusted(monkeypatch):
    monkeypatch.setattr(get_settings(), "TRUSTED_PROXY_IPS", "", raising=False)
    yield


# ---------------------------------------------------------------------------
# The regression: more than one proxy
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_two_proxies_still_record_the_real_client(trusted):
    """The case that breaks the old implementation.

    With Caddy in front of nginx the chain is `client, caddy` and the last entry
    is an internal address. Walking from the right past trusted hops finds the
    client whatever the hop count.
    """
    request = _Request(PROXY_IP, forwarded=f"{CLIENT}, {EDGE_IP}")

    assert _client_ip(request) == CLIENT


@pytest.mark.asyncio
async def test_one_proxy_records_the_real_client(trusted):
    """The arrangement that already worked, which must keep working."""
    request = _Request(PROXY_IP, forwarded=CLIENT)

    assert _client_ip(request) == CLIENT


# ---------------------------------------------------------------------------
# Forgery
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_untrusted_caller_cannot_choose_the_recorded_address(untrusted):
    """Reaching the API directly and naming someone else must not write that
    name into a legal record."""
    request = _Request(CLIENT, forwarded="1.2.3.4")

    assert _client_ip(request) == CLIENT


@pytest.mark.asyncio
async def test_a_prepended_hop_through_a_trusted_proxy_is_ignored(trusted):
    """The client controls the left of the chain; the proxy appends to it."""
    request = _Request(PROXY_IP, forwarded=f"1.2.3.4, {CLIENT}")

    assert _client_ip(request) == CLIENT


@pytest.mark.asyncio
async def test_malformed_entries_are_not_recorded(trusted):
    request = _Request(PROXY_IP, forwarded=f"junk, not-an-ip, {CLIENT}")

    assert _client_ip(request) == CLIENT


# ---------------------------------------------------------------------------
# The column's contract
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_client_records_null_not_a_sentinel(untrusted):
    """UserConsent.ip_address is nullable. NULL says "not recorded"; the
    resolver's "unknown" string would read as a value that was."""
    assert _client_ip(_Request(None)) is None


@pytest.mark.asyncio
async def test_the_value_fits_the_column(trusted):
    """ip_address is String(45); an over-long value would raise on flush."""
    long_v6 = "0000:0000:0000:0000:0000:ffff:192.168.100.228%enp0s31f6xxxxx"

    request = _Request(PROXY_IP, forwarded=long_v6)
    result = _client_ip(request)

    assert result is None or len(result) <= 45


@pytest.mark.asyncio
async def test_a_direct_caller_is_recorded_as_itself(untrusted):
    assert _client_ip(_Request(CLIENT)) == CLIENT


# ---------------------------------------------------------------------------
# One implementation, not two
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_header_is_parsed_in_exactly_one_place():
    """Two copies of this logic is how the two drifted apart: the rate limiter
    became trusted-proxy-aware while consent records did not."""
    import inspect

    from app.services import consent_service

    source = inspect.getsource(consent_service._client_ip)

    assert "client_ip_from" in source

    # The docstring explains the header, so match on the ACT of reading it
    # rather than on the name appearing anywhere in the source.
    body = source.split('"""')[-1]

    assert "headers.get" not in body, "consent_service reads the header directly again"
    assert "request.client" not in body, "consent_service inspects the peer directly again"
