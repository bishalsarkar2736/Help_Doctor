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


