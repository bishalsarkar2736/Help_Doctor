import json
import logging
from typing import Any, Optional

from app.db.redis import get_redis

logger = logging.getLogger(__name__)


async def get_cache(key: str) -> Optional[Any]:
    """Read a cached value.

    Fails open: if Redis is unreachable this returns None (a cache miss) so the
    caller degrades to its source of truth (the DB) instead of erroring.
    """
    try:
        redis = await get_redis()
        data = await redis.get(key)
    except Exception:
        logger.warning("cache_unavailable", extra={"op": "get", "key": key})
        return None

    if not data:
        return None

    try:
        if isinstance(data, bytes):
            data = data.decode()

        return json.loads(data)

    except Exception:
        return None


async def set_cache(key: str, value: Any, ttl: int = 60):
    """Best-effort cache write; a Redis outage is logged and ignored."""
    try:
        redis = await get_redis()
        await redis.set(
            key,
            json.dumps(value),
            ex=ttl,
        )
    except Exception:
        logger.warning("cache_unavailable", extra={"op": "set", "key": key})


async def delete_cache(key: str):
    """Best-effort cache invalidation; a Redis outage is logged and ignored."""
    try:
        redis = await get_redis()
        await redis.delete(key)
    except Exception:
        logger.warning("cache_unavailable", extra={"op": "delete", "key": key})
