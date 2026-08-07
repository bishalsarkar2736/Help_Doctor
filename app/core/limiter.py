from slowapi import Limiter
from slowapi.util import get_remote_address

from app.config import get_settings

settings = get_settings()

# In-memory by default (per-process); set RATE_LIMIT_STORAGE_URI to a shared
# backend (e.g. async+redis://) for distributed limits across replicas.
# swallow_errors=True fails OPEN if the storage backend is unreachable, so a
# Redis outage never turns rate limiting into a hard 500.
limiter = Limiter(
    key_func=get_remote_address,
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

    return get_remote_address(request)


