from app.websocket.manager import manager


async def broadcast_presence(
    *,
    user_id: int,
    online: bool,
):

    await manager.broadcast_channel(
        "presence_updates",
        {
            "version": 1,
            "event": "presence_update",
            "data": {
                "user_id": user_id,
                "online": online,
            },
        },
    )