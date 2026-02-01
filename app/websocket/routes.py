from fastapi import APIRouter, WebSocket, Depends
from app.websocket.manager import manager
from app.security.jwt import decode_token_from_ws

router = APIRouter()


@router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
):
    user = await decode_token_from_ws(websocket)
    user_id = user.id

    await manager.connect(user_id, websocket)

    try:
        while True:
            await websocket.receive_text()
    except:
        manager.disconnect(user_id)
