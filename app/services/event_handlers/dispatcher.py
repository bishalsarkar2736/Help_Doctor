from sqlalchemy.ext.asyncio import AsyncSession

from app.services.event_handlers.notification_handler import (
    handle_notification_event,
)

from app.services.event_handlers.prescription_email_handler import (
    handle_prescription_issued_email,
)


async def handle_prescription_issued(
    *,
    db:AsyncSession,
    validated,
    event_id,
    event_type,
):
    # Existing notification flow
    await handle_notification_event(
        db=db,
        validated=validated,
        event_id=event_id,
        event_type=event_type,
    )

    # Email delivery
    await handle_prescription_issued_email(
        db=db,
        validated=validated,
        event_id=event_id,
    )



EVENT_HANDLERS = {
    "APPOINTMENT_STATUS_CHANGED":
        handle_notification_event,

    "APPOINTMENT_CREATED":
        handle_notification_event,

    "APPOINTMENT_CONFIRMED":
        handle_notification_event,

    "APPOINTMENT_CANCELLED":
        handle_notification_event,

    "APPOINTMENT_RESCHEDULED":
        handle_notification_event,

    "APPOINTMENT_RESCHEDULE_REQUEST":
        handle_notification_event,

    "PAYMENT_SUCCESS":
        handle_notification_event,

    # Was missing. The event had a schema AND a notification with a written
    # message, but dispatch_event found no handler and returned, so a refunded
    # patient was never told. Silently: no error, no dead letter.
    "PAYMENT_REFUNDED":
        handle_notification_event,

    "CONSULTATION_STARTED":
        handle_notification_event,

    "PATIENT_NEXT_IN_QUEUE":
        handle_notification_event,
    
    "CONSULTATION_COMPLETED":
        handle_notification_event,

    "PRESCRIPTION_CREATED":
        handle_notification_event,

    # "PRESCRIPTION_ISSUED":
    #     handle_notification_event,

    "PRESCRIPTION_ISSUED":
        handle_prescription_issued,

    "PRESCRIPTION_UPDATED":
        handle_notification_event,

    "PRESCRIPTION_REVISED":
        handle_notification_event,
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