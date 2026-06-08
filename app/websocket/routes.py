from fastapi import APIRouter, WebSocket
from starlette.websockets import WebSocketDisconnect

from app.websocket.manager import manager
from app.security.jwt import decode_token_from_ws

from app.services.presence_service import (
    set_user_online,
    set_user_offline,
)
from app.models.user import UserRole
from app.services.notification_receipt_service import (
    mark_notification_delivered,
    mark_notifications_seen,
)

from app.services.presence_broadcast_service import (
    broadcast_presence,
)

from app.schemas.websocket import (
    PingMessage,
    NotificationDeliveredMessage,
    NotificationSeenMessage,
    SubscribeMessage,
    UnsubscribeMessage,
)

from app.core.ws_metrics import (
    websocket_messages_total,
    websocket_errors_total,
)

import logging

logger = logging.getLogger(__name__)

router = APIRouter()


@router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
):

    user = await decode_token_from_ws(
        websocket
    )

    # Authentication failed
    if not user:
        return

    user_id = user.id

    connected = await manager.connect(
        user_id,
        websocket,
    )

    if not connected:
        return

    # DEFAULT SUBSCRIPTIONS

    if user.role == UserRole.ADMIN:

        await manager.subscribe(
            "admin_dashboard",
            websocket,
        )

        await manager.subscribe(
            "presence_updates",
            websocket,
        )

    # PRESENCE ONLINE

    await set_user_online(user_id)

    await broadcast_presence(
        user_id=user_id,
        online=True,
    )

    try:

        while True:

            try:

                # Keeps connection alive
                data = await websocket.receive_json()

            
            except WebSocketDisconnect:

                logger.info(
                    "ws_client_disconnected",
                    extra={
                        "user_id": user_id,
                    },
                )

                break

            event = data.get("event")

            websocket_messages_total.inc()

            

            # refresh TTL heartbeat
            await set_user_online(user_id)


            # PING / PONG

            if event == "ping":

                try:
                    PingMessage.model_validate(data)

                except Exception:

                    await websocket.send_json({
                        "version": 1,
                        "event": "error",
                        "message": "invalid_ping_payload",
                    })

                    continue

                await websocket.send_json({
                    "version": 1,
                    "event": "pong",
                })

            # NOTIFICATION DELIVERED

            elif event == "notification_delivered":

                try:
                    payload = (
                        NotificationDeliveredMessage
                        .model_validate(data)
                    )

                except Exception:

                    await websocket.send_json({
                        "version": 1,
                        "event": "error",
                        "message": (
                            "invalid_notification_delivered_payload"
                        ),
                    })

                    continue

                await mark_notification_delivered(
                    notification_id=payload.notification_id,
                    user_id=user_id,
                )

                await websocket.send_json({
                    "version": 1,
                    "event": "notification_delivered_ack",
                    "notification_id": payload.notification_id,
                })


            # NOTIFICATION SEEN

            elif event == "notification_seen":

                try:
                    payload = (
                        NotificationSeenMessage
                        .model_validate(data)
                    )

                except Exception:

                    await websocket.send_json({
                        "version": 1,
                        "event": "error",
                        "message": (
                            "invalid_notification_seen_payload"
                        ),
                    })

                    continue

                try:

                    await mark_notifications_seen(
                        notification_ids=payload.notification_ids,
                        user_id=user_id,
                    )

                    await websocket.send_json({
                        "version": 1,
                        "event": "notification_seen_ack",
                        "notification_ids": payload.notification_ids,
                    })

                except Exception as exc:

                    websocket_errors_total.inc()

                    logger.exception(
                        "notification_seen_failed",
                        extra={
                            "user_id": user_id,
                            "error": str(exc),
                        },
                    )

                    await websocket.send_json({
                        "version": 1,
                        "event": "error",
                        "message": "notification_seen_failed",
                    })

                    continue


            
            # DYNAMIC CHANNEL SUBSCRIBE

            elif event == "subscribe":

                try:
                    payload = (
                        SubscribeMessage
                        .model_validate(data)
                    )

                except Exception:

                    await websocket.send_json({
                        "version": 1,
                        "event": "error",
                        "message": (
                            "invalid_subscribe_payload"
                        ),
                    })

                    continue

                await manager.subscribe(
                    payload.channel,
                    websocket,
                )

                await websocket.send_json({
                    "version": 1,
                    "event": "subscribed",
                    "channel": payload.channel,
                })

            
            # DYNAMIC CHANNEL UNSUBSCRIBE

            elif event == "unsubscribe":

                try:
                    payload = (
                        UnsubscribeMessage
                        .model_validate(data)
                    )

                except Exception:

                    await websocket.send_json({
                        "version": 1,
                        "event": "error",
                        "message": (
                            "invalid_unsubscribe_payload"
                        ),
                    })

                    continue

                await manager.unsubscribe(
                    payload.channel,
                    websocket,
                )

                await websocket.send_json({
                    "version": 1,
                    "event": "unsubscribed",
                    "channel": payload.channel,
                })


            # UNKNOWN EVENT

            else:

                await websocket.send_json({
                    "version": 1,
                    "event": "error",
                    "message": "unknown_event",
                })



    # except WebSocketDisconnect:

    #     logger.info(
    #         "ws_client_disconnected",
    #         extra={
    #             "user_id": user_id,
    #         },
    #     )


    except Exception as e:

        websocket_errors_total.inc()


        logger.exception(
            "ws_unexpected_error",
            extra={
                "user_id": user_id,
                "error": str(e),
            },
        )

    finally:

        # print("FINALLY DISCONNECT:", user_id)

        # if user.role == UserRole.ADMIN:

        #     await manager.unsubscribe(
        #         "admin_dashboard",
        #         websocket,
        #     )

        #     await manager.unsubscribe(
        #         "presence_updates",
        #         websocket,
        #     )

        # await set_user_offline(user_id)

        # await broadcast_presence(
        #     user_id=user_id,
        #     online=False,
        # )

        # await manager.disconnect(
        #     user_id,
        #     websocket,
        # )




        # try:
        #     if user.role == UserRole.ADMIN:

        #         await manager.unsubscribe(
        #             "admin_dashboard",
        #             websocket,
        #         )

        #         await manager.unsubscribe(
        #             "presence_updates",
        #             websocket,
        #         )

        #     await set_user_offline(user_id)

        #     await broadcast_presence(
        #         user_id=user_id,
        #         online=False,
        #     )

        # except Exception as exc:
        #     logger.exception(
        #         "ws_cleanup_failed",
        #         extra={
        #             "user_id": user_id,
        #             "error": str(exc),
        #         },
        #     )

        # finally:
        #     await manager.disconnect(
        #         user_id,
        #         websocket,
        #     )



        try:
            if user.role == UserRole.ADMIN:
                try:
                    await manager.unsubscribe("admin_dashboard", websocket)
                except Exception:
                    logger.exception("unsubscribe_admin_failed", extra={"user_id": user_id})

                try:
                    await manager.unsubscribe("presence_updates", websocket)
                except Exception:
                    logger.exception("unsubscribe_presence_failed", extra={"user_id": user_id})

            try:
                await set_user_offline(user_id)
            except Exception:
                logger.exception("set_user_offline_failed", extra={"user_id": user_id})

            try:
                await broadcast_presence(user_id=user_id, online=False)
            except Exception:
                logger.exception("broadcast_presence_failed", extra={"user_id": user_id})

        finally:
            await manager.disconnect(user_id, websocket)