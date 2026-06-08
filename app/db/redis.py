# import redis.asyncio as redis
# from app.config import get_settings


# settings = get_settings()

# redis_client = redis.from_url(
#     settings.REDIS_URL,
#     decode_responses=True,
# )


# async def get_redis():
#     return redis_client

import redis.asyncio as redis

from app.config import get_settings

settings = get_settings()


async def get_redis():

    return redis.from_url(
        settings.REDIS_URL,
        decode_responses=True,
    )