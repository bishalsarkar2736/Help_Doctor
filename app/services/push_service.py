import json
import os

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pywebpush import webpush, WebPushException

from app.models.push_subscription import PushSubscription
from app.db.redis import get_redis
from app.db.postgres import AsyncSessionLocal

VAPID_PRIVATE_KEY = os.getenv("VAPID_PRIVATE_KEY")
VAPID_EMAIL = os.getenv("VAPID_EMAIL")


from app.db.postgres import AsyncSessionLocal

async def send_push_to_user(
    *,
    user_id: int,
    payload: dict,
):
    async with AsyncSessionLocal() as db:

        redis = await get_redis()
        key = f"push_limit:{user_id}"

        if await redis.get(key):
            return

        await redis.set(key, "1", ex=2)

        result = await db.execute(
            select(PushSubscription).where(
                PushSubscription.user_id == user_id
            )
        )

        subs = result.scalars().all()

        for sub in subs:
            try:
                webpush(
                    subscription_info={
                        "endpoint": sub.endpoint,
                        "keys": sub.keys,
                    },
                    data=json.dumps(payload),
                    vapid_private_key=VAPID_PRIVATE_KEY,
                    vapid_claims={"sub": VAPID_EMAIL},
                )

            except WebPushException as e:
                if e.response and e.response.status_code in (404, 410):
                    await db.delete(sub)

        await db.commit()