import asyncio
import json
import logging

from app.db.redis import get_redis
from app.websocket.manager import manager

CHANNEL_NAME = "ws_notifications"

REDIS_RECONNECT_DELAY = 5

logger = logging.getLogger(__name__)


async def redis_listener():
    """
    Redis Pub/Sub listener.

    Receives websocket events from:
    - outbox workers
    - FastAPI workers
    - background tasks

    Then fans out locally to websocket clients.
    """

    while True:

        pubsub = None

        try:

            logger.info(
                "redis_listener_starting"
            )

            redis = await get_redis()

            pubsub = redis.pubsub()

            await pubsub.subscribe(
                CHANNEL_NAME
            )

            logger.info(
                "redis_listener_subscribed",
                extra={
                    "channel": CHANNEL_NAME,
                },
            )

            async for message in pubsub.listen():

                if (
                    message["type"]
                    != "message"
                ):
                    continue

                try:

                    data = json.loads(
                        message["data"]
                    )

                except Exception:

                    logger.warning(
                        "invalid_redis_payload"
                    )

                    continue

                user_id = data.get(
                    "user_id"
                )

                if not user_id:

                    logger.warning(
                        "missing_user_id"
                    )

                    continue

                # remove internal routing field
                payload = dict(data)

                payload.pop(
                    "user_id",
                    None,
                )

                # frontend stability defaults
                payload.setdefault(
                    "message",
                    None,
                )

                payload.setdefault(
                    "appointment_id",
                    None,
                )

                payload.setdefault(
                    "event",
                    "notification",
                )

                await manager.send_local(
                    user_id=user_id,
                    data=payload,
                )

        except Exception as e:

            logger.exception(
                "redis_listener_crashed",
                extra={
                    "error": str(e),
                },
            )

            await asyncio.sleep(
                REDIS_RECONNECT_DELAY
            )

        finally:

            if pubsub:

                try:
                    await pubsub.close()

                except Exception:
                    pass