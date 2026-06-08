import json
from typing import Any, Optional

from app.db.redis import get_redis


async def get_cache(key: str) -> Optional[Any]:

    redis = await get_redis()

    data = await redis.get(key)

    if not data:
        return None

    try:
        if isinstance(data, bytes):
            data = data.decode()

        return json.loads(data)

    except Exception:
        return None


async def set_cache(key: str, value: Any, ttl: int = 60):

    redis = await get_redis()

    await redis.set(
        key,
        json.dumps(value),
        ex=ttl
    )


async def delete_cache(key: str):
    
    redis = await get_redis()

    await redis.delete(key)