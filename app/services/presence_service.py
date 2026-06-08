from app.db.redis import get_redis

PRESENCE_TTL = 30


async def set_user_online(user_id: int):

    redis = await get_redis()

    await redis.set(
        f"presence:user:{user_id}",
        "online",
        ex=PRESENCE_TTL,
    )


async def set_user_offline(user_id: int):

    redis = await get_redis()

    await redis.delete(
        f"presence:user:{user_id}"
    )


async def is_user_online(user_id: int) -> bool:

    redis = await get_redis()

    exists = await redis.exists(
        f"presence:user:{user_id}"
    )

    return bool(exists)