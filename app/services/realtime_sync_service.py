from app.websocket.manager import manager


async def send_realtime_sync(
    *,
    user_id: int,
    payload: dict,
):
    """
    Realtime system sync events.

    Examples:
    - dashboard refresh
    - admin panel updates
    - user status changes
    - appointment board refresh

    Does NOT respect notification preferences.
    """

    await manager.notify_user(
        user_id=user_id,
        message=payload,
    )