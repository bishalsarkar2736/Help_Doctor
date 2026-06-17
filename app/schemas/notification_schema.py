from datetime import datetime

from pydantic import BaseModel
from pydantic import ConfigDict
from app.models.notification import (
    NotificationCategory,
)


class NotificationResponse(
    BaseModel,
):
    model_config = ConfigDict(
        from_attributes=True
    )

    id: int

    title: str

    message: str

    category: NotificationCategory

    related_appointment_id: int | None

    read_at: datetime | None

    seen_at: datetime | None

    delivered_at: datetime | None

    created_at: datetime


class NotificationUnreadCountResponse(
    BaseModel,
):
    count: int


class NotificationMarkReadResponse(
    BaseModel,
):
    message: str


class NotificationMarkAllReadResponse(
    BaseModel,
):
    message: str
    updated: int