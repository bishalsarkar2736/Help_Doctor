"""The caller's address, for per-IP limits.

Shared because two assistants need it and one copy can be wrong in one place.
"""

from fastapi import Request


def client_ip_from(request: Request) -> str:
    """The original client, not the proxy in front of it.

    X-Forwarded-For first: nginx sits ahead of the API, so request.client is
    the proxy and every visitor would otherwise share one rate-limit bucket —
    the first twenty questions a minute would exhaust it for everyone.
    """
    forwarded = request.headers.get("x-forwarded-for", "")

    if forwarded:
        # Left-most entry is the original client; the rest are proxies.
        return forwarded.split(",")[0].strip()

    return request.client.host if request.client else "unknown"
