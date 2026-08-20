from slowapi import Limiter

from app.config import get_settings
from app.utils.request_ip import client_ip_from

settings = get_settings()

# In-memory by default (per-process); set RATE_LIMIT_STORAGE_URI to a shared
# backend (e.g. async+redis://) for distributed limits across replicas.
# swallow_errors=True fails OPEN if the storage backend is unreachable, so a
# Redis outage never turns rate limiting into a hard 500.
# key_func is client_ip_from, NOT slowapi's get_remote_address.
#
# get_remote_address returns request.client.host, which behind a reverse proxy
# is the proxy — so every anonymous caller shared one bucket and a per-IP limit
# throttled the whole internet together while stopping no individual. That was
# already true for traffic arriving through the frontend's /api proxy.
#
# client_ip_from reads X-Forwarded-For only when the peer is a configured
# trusted proxy, so this does not become a header anyone can set to mint
# themselves a fresh budget.
limiter = Limiter(
    key_func=client_ip_from,
    storage_uri=settings.RATE_LIMIT_STORAGE_URI or "memory://",
    swallow_errors=True,
)


def authenticated_key(request) -> str:
    """Rate-limit key: the signed-in user, falling back to their address.

    The default key is the client IP, which is the right choice for the public
    endpoints — an anonymous caller has no other identity. It is the wrong one
    for staff endpoints, in both directions:

    - A clinic sits behind one office connection, so every receptionist,
      doctor and admin at that site shares an address. An IP limit meant to
      slow one account down instead throttles a whole front desk at once.
    - A stolen token used from somewhere else lands on a different address and
      gets a full budget of its own, which is the case the limit exists for.

    Keyed on the token's subject instead. This is not an authentication
    decision and must not be read as one: the endpoint's own dependency
    verifies the token properly and rejects the request if it does not hold.
    All this needs is a stable identifier to count against, so an unreadable
    token falls back to the address rather than raising — the request is about
    to be refused anyway.
    """
    # Imported here rather than at module scope: app.security.jwt pulls in the
    # database session factory, and app.core is meant to sit below that. A
    # top-level import would invert the layering for one function call.
    from app.security.jwt import decode_access_token

    header = request.headers.get("Authorization", "")

    if header.startswith("Bearer "):
        payload = decode_access_token(header[len("Bearer "):])

        if payload and payload.get("sub"):
            return f"user:{payload['sub']}"

    return client_ip_from(request)


