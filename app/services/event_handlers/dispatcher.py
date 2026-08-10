from sqlalchemy.ext.asyncio import AsyncSession

from app.services.event_handlers.notification_handler import (
    EVENT_NOTIFICATION_CONFIG,
    handle_notification_event,
)
from app.services.event_handlers.notification_email_handler import (
    handle_notification_email,
)
from app.services.event_handlers.notification_whatsapp_handler import (
    handle_notification_whatsapp,
)

async def _with_patient_channels(
    *,
    db: AsyncSession,
    validated,
    event_id,
    event_type,
):
    """The in-app notification, then the patient's out-of-band channels.

    Composed in this order deliberately: handle_notification_event validates the
    recipient and raises RecipientNotPartyToEvent for a wrong one, so the channels
    are only ever reached for a recipient that has already been accepted. Each
    channel handler narrows that to the patient; neither re-authorises.

    Built as one wrapper rather than five near-identical ones, and it reads the
    recipient field from EVENT_NOTIFICATION_CONFIG so email and the notification
    can never disagree about who the event is addressed to.
    """
    await handle_notification_event(
        db=db,
        validated=validated,
        event_id=event_id,
        event_type=event_type,
    )

    config = EVENT_NOTIFICATION_CONFIG.get(event_type)

    if not config:
        return

    await handle_notification_email(
        db=db,
        validated=validated,
        event_id=event_id,
        event_type=event_type,
        user_field=config["user_field"],
    )

    # Same recipient field, so the two channels cannot disagree about who the
    # event is for. Each has its own allowlist and its own preference, so the
    # set of events they cover is allowed to differ — and does.
    await handle_notification_whatsapp(
        db=db,
        validated=validated,
        event_id=event_id,
        event_type=event_type,
        user_field=config["user_field"],
    )


EVENT_HANDLERS = {
    "APPOINTMENT_STATUS_CHANGED":
        handle_notification_event,

    "APPOINTMENT_CREATED":
        handle_notification_event,

    "APPOINTMENT_CONFIRMED":
        _with_patient_channels,

    "APPOINTMENT_CANCELLED":
        _with_patient_channels,

    "APPOINTMENT_RESCHEDULED":
        _with_patient_channels,

    # Reaches the channels because a reminder is precisely the kind of thing a
    # patient wants out of band. Note the event is published by a scheduled job
    # but carries source=USER: SYSTEM suppresses the in-app notification, and
    # that notification is the row the WhatsApp receipt is written on, so a
    # SYSTEM reminder would have nowhere to record delivery even if it sent.
    "APPOINTMENT_REMINDER":
        _with_patient_channels,

    "APPOINTMENT_RESCHEDULE_REQUEST":
        handle_notification_event,

    # Routed through the composite so WhatsApp can reach it. Email is unaffected:
    # EMAIL_EVENTS does not list PAYMENT_SUCCESS, so the composite runs the email
    # handler and it returns immediately. That is the point of each channel owning
    # its own allowlist — a route can be opened for one channel without opening it
    # for the others.
    "PAYMENT_SUCCESS":
        _with_patient_channels,

    # Was missing. The event had a schema AND a notification with a written
    # message, but dispatch_event found no handler and returned, so a refunded
    # patient was never told. Silently: no error, no dead letter.
    "PAYMENT_REFUNDED":
        _with_patient_channels,

    "CONSULTATION_STARTED":
        handle_notification_event,

    "PATIENT_NEXT_IN_QUEUE":
        handle_notification_event,
    
    "CONSULTATION_COMPLETED":
        handle_notification_event,

    "PRESCRIPTION_CREATED":
        handle_notification_event,

    "PRESCRIPTION_ISSUED":
        _with_patient_channels,

    "PRESCRIPTION_UPDATED":
        handle_notification_event,

    "PRESCRIPTION_REVISED":
        _with_patient_channels,
}


async def dispatch_event(
    *,
    db: AsyncSession,
    event_type: str,
    validated,
    event_id,
):
    
    normalized_event_type = event_type.strip().upper()

    #handler = EVENT_HANDLERS.get(event_type)

    handler = EVENT_HANDLERS.get(normalized_event_type)

    if not handler:
        return


    await handler(
        db=db,
        validated=validated,
        event_id=event_id,
        event_type=normalized_event_type,
    )