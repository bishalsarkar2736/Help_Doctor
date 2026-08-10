from pydantic import BaseModel


class NotificationPreferenceResponse(BaseModel):
    email_enabled: bool
    # Unlike the other three, this one defaults to False: WhatsApp is opt-in.
    # It was consumed by the delivery handler while being absent from here,
    # which made it unreadable and unchangeable — so the channel could never
    # deliver anything, whatever the server was configured to do.
    whatsapp_enabled: bool
    push_enabled: bool
    realtime_enabled: bool


class NotificationPreferenceUpdate(BaseModel):
    # Every field optional: a PATCH carries only the toggles that changed, and
    # an omitted one is left alone rather than reset. There is deliberately no
    # user_id here — the subject is the authenticated caller, so one user cannot
    # address another's preferences.
    email_enabled: bool | None = None
    whatsapp_enabled: bool | None = None
    push_enabled: bool | None = None
    realtime_enabled: bool | None = None