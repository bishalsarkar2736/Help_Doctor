"""The caller's address, for per-IP limits.

Shared because several call sites need it and one copy can be wrong in one
place: the rate limiter, the medicine assistant and the scheduling assistant
all count against whatever this returns.

THE HEADER IS NOT EVIDENCE BY ITSELF.
--------------------------------------
X-Forwarded-For is written by whoever connected. This function believed it
unconditionally, which is correct behind a proxy that overwrites it and wrong
everywhere else — and the API is published on :8000 today, so a caller who
reached it directly could name any address and get a fresh rate-limit budget
for each one. Per-IP limits then stop anybody who is not trying to evade them.

So the header is read only when the immediate peer is a proxy this deployment
was told to trust (TRUSTED_PROXY_IPS). Unset means trust nothing, which is the
default and is the safe direction: the worst case is that everyone behind a
proxy shares one bucket, which is too strict rather than too permissive.
"""

import ipaddress

from fastapi import Request

from app.config import get_settings


def _parse(value: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        return ipaddress.ip_address(value.strip())

    except ValueError:
        return None


def _is_trusted(address: str, networks: tuple) -> bool:
    parsed = _parse(address)

    if parsed is None:
        return False

    return any(parsed in network for network in networks)


def client_ip_from(request: Request) -> str:
    """The original client, not the proxy in front of it.

    Walks X-Forwarded-For from the RIGHT, skipping addresses that are
    themselves trusted proxies, and returns the first one that is not. The
    right-hand entries are the ones each proxy appended and therefore the ones
    an attacker cannot fake; the left-hand entries are whatever the original
    request carried, which a client can pre-populate to impersonate any
    address.
    """
    peer = request.client.host if request.client else None

    networks = get_settings().trusted_proxy_networks

    if peer and networks and _is_trusted(peer, networks):
        forwarded = request.headers.get("x-forwarded-for", "")

        for candidate in reversed(forwarded.split(",")):
            candidate = candidate.strip()

            if not candidate or _parse(candidate) is None:
                # Malformed entries are skipped rather than returned: a value
                # like "not-an-ip" would otherwise become its own rate-limit
                # bucket, which is exactly the evasion this guards against.
                continue

            if not _is_trusted(candidate, networks):
                return candidate

    return peer or "unknown"
