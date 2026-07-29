import asyncio

import redis.asyncio as redis

from app.config import get_settings

settings = get_settings()

# One client (with its own connection pool) per event loop. In production
# there's a single loop, so this is effectively a reused singleton; under the
# test suite (a fresh loop per test) each loop gets its own client, avoiding the
# "attached to a different loop" error that a process-wide singleton causes.
_clients: "dict[asyncio.AbstractEventLoop, redis.Redis]" = {}


async def get_redis():
    loop = asyncio.get_running_loop()

    client = _clients.get(loop)
    if client is None:
        client = redis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
        )
        _clients[loop] = client

    return client
