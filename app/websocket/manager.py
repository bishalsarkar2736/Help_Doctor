from fastapi import WebSocket
from typing import Dict


class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[int, WebSocket] = {}

    async def connect(self, user_id: int, websocket: WebSocket):
        await websocket.accept()
        self.active_connections[user_id] = websocket

    def disconnect(self, user_id: int):
        self.active_connections.pop(user_id, None)

    async def notify_user(self, user_id: int, message: str):
        websocket = self.active_connections.get(user_id)
        if websocket:
            await websocket.send_text(message)


manager = ConnectionManager()
