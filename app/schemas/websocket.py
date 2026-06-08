from pydantic import BaseModel
from typing import Literal, Any


class WSMessage(BaseModel):
    event: str
    data: dict | list | str | None = None


class PingMessage(BaseModel):
    event: Literal["ping"]


class PongMessage(BaseModel):
    event: Literal["pong"]


class NotificationDeliveredMessage(BaseModel):
    event: Literal["notification_delivered"]
    notification_id: int


class NotificationSeenMessage(BaseModel):
    event: Literal["notification_seen"]
    notification_ids: list[int]


class SubscribeMessage(BaseModel):
    event: Literal["subscribe"]
    channel: str


class UnsubscribeMessage(BaseModel):
    event: Literal["unsubscribe"]
    channel: str