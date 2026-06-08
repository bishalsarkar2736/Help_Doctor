from pydantic import BaseModel


class NotificationPreferenceResponse(BaseModel):
    email_enabled: bool
    push_enabled: bool
    realtime_enabled: bool


class NotificationPreferenceUpdate(BaseModel):
    email_enabled: bool | None = None
    push_enabled: bool | None = None
    realtime_enabled: bool | None = None