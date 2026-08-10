import logging
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.notification_service import notify_user

from app.services.realtime_dashboard_service import (
    publish_dashboard_update,
)

from app.services.realtime_notification_service import (
    send_realtime_notification,
)
from app.models.notification import (
    NotificationCategory,
)
from app.models.appointment import Appointment
from app.models.doctor import Doctor
from app.services.notification_preference_service import (
    get_or_create_preferences,
)
from app.schemas.event_metadata import EventSource

logger = logging.getLogger(__name__)

EVENT_NOTIFICATION_CONFIG = {

    "APPOINTMENT_CREATED": {
        "title": "Appointment Created",
        "message": "A new appointment has been booked",
        "category": NotificationCategory.APPOINTMENT,
        "user_field": "user_id",
        "appointment_field": "appointment_id",
    },

    "APPOINTMENT_CONFIRMED": {
        "title": "Appointment Confirmed",
        "message": "Your appointment has been confirmed",
        "category": NotificationCategory.APPOINTMENT,
        "user_field": "user_id",
        "appointment_field": "appointment_id",
    },

    "APPOINTMENT_CANCELLED": {
        "title": "Appointment Cancelled",
        "message": "Your appointment has been cancelled",
        "category": NotificationCategory.APPOINTMENT,
        "user_field": "user_id",
        "appointment_field": "appointment_id",
    },

    "APPOINTMENT_RESCHEDULED": {
        "title": "Appointment Rescheduled",
        "message": "Your appointment has been rescheduled",
        "category": NotificationCategory.APPOINTMENT,
        "user_field": "user_id",
        "appointment_field": "appointment_id",
    },

    "APPOINTMENT_REMINDER": {
        "title": "Appointment Reminder",
        "message": "You have an upcoming appointment",
        "category": NotificationCategory.APPOINTMENT,
        "user_field": "user_id",
        "appointment_field": "appointment_id",
    },

    "APPOINTMENT_RESCHEDULE_REQUEST": {
        "title": "Reschedule Request",
        "message": "A patient requested to reschedule an appointment",
        "category": NotificationCategory.APPOINTMENT,
        "user_field": "user_id",
        "appointment_field": "appointment_id",
    },

    "PAYMENT_SUCCESS": {
        "title": "Payment Successful",
        "message": "Your payment was successful",
        "category": NotificationCategory.PAYMENT,
        "user_field": "user_id",
        "appointment_field": "appointment_id",
    },

    "PAYMENT_REFUNDED": {
        "title": "Payment Refunded",
        "message_template": (
            "Your payment of ৳{refunded_amount} has been refunded"
        ),
        "category": NotificationCategory.PAYMENT,
        "user_field": "user_id",
        "appointment_field": "appointment_id",
    },

    "APPOINTMENT_STATUS_CHANGED": {
        "title": "Appointment Update",
        "message_template": (
            "Your appointment status changed to {new_status}"
        ),
        "category": NotificationCategory.APPOINTMENT,
        "user_field": "patient_id",
        "appointment_field": "appointment_id",
    },

    "CONSULTATION_STARTED": {
        "title": "Consultation Started",
        "message": "Your consultation has started",
        "category": NotificationCategory.APPOINTMENT,
        "user_field": "patient_id",
        "appointment_field": "appointment_id",
    },

    "PATIENT_NEXT_IN_QUEUE": {
        "title": "You're Next",
        "message": (
            "Please proceed to the consultation room. "
            "You are next in the queue."
        ),
        "category": NotificationCategory.APPOINTMENT,
        "user_field": "patient_id",
        "appointment_field": "appointment_id",
    },
    
    "CONSULTATION_COMPLETED": {
        "title": "Consultation Completed",
        "message": "Your consultation has been completed.",
        "category": NotificationCategory.APPOINTMENT,
        "user_field": "patient_id",
        "appointment_field": "appointment_id",
    },

    "PRESCRIPTION_CREATED": {
        "title": "Prescription Created",
        "message": "Doctor created your prescription draft",
        "category": NotificationCategory.PRESCRIPTION,
        "user_field": "patient_id",
        "appointment_field": "appointment_id",
    },

    "PRESCRIPTION_ISSUED": {
        "title": "Prescription Issued",
        "message": "Your prescription is ready",
        "category": NotificationCategory.PRESCRIPTION,
        "user_field": "patient_id",
        "appointment_field": "appointment_id",
    },

    "PRESCRIPTION_UPDATED": {
        "title": "Prescription Updated",
        "message": "Your prescription was updated",
        "category": NotificationCategory.PRESCRIPTION,
        "user_field": "patient_id",
        "appointment_field": "appointment_id",
    },

    "PRESCRIPTION_REVISED": {
        "title": "Prescription Revised",
        "message": "A revised prescription has been issued",
        "category": NotificationCategory.PRESCRIPTION,
        "user_field": "patient_id",
        "appointment_field": "appointment_id",
    },
}


class RecipientNotPartyToEvent(Exception):
    """A notification was addressed to somebody the event is not about.

    Raised rather than skipped. This can only fire on a programming error — a
    publisher naming the wrong user — and the safe response to "we are about to
    tell the wrong person" is to not send, loudly. The outbox retries and then
    dead-letters the event, so it is preserved for inspection instead of
    disappearing into a log line.

    Defined here rather than reusing the worker's NonRetryableError: a service
    importing a worker internal inverts the layering, and the generic retry path
    reaches the dead-letter queue anyway. The cost is a few doomed retries first.

    Note this also stops the composite PRESCRIPTION_ISSUED handler from sending
    its email, because that runs after this one. That is correct: if the
    recipient is wrong, no channel should carry the message.
    """


async def _assert_recipient_is_party_to_event(
    db: AsyncSession,
    *,
    event_type: str,
    user_field: str,
    recipient_id: int,
    appointment_id: int | None,
) -> None:
    """The recipient must be someone the event is actually about.

    Nothing checked this. The handler delivered to whatever user id the event
    named, so a publisher naming the wrong person produced a correctly formatted
    message sent to a stranger — which is exactly what PAYMENT_REFUNDED did,
    addressing "Your payment has been refunded" to the administrator who issued
    it. Wiring alone would not have caught that; this is the layer that does.

    HOW THE CLINIC IS ESTABLISHED
    Not by comparing clinic ids, which for a patient would mean nothing —
    patients are global identities and belong to every clinic that has treated
    them. Instead the allowed set is derived FROM the appointment the event is
    about: its patient, and its doctor's user. Both are of that appointment's
    clinic by construction, so "belongs to the event's clinic" is structural
    rather than a comparison that could be written the wrong way round. A user
    from another clinic cannot be in the set.

    Every notification configuration resolves through appointment_id, and
    Payment.appointment_id is NOT NULL, so this is available on all of them.

    HOW THE TYPE IS ESTABLISHED
    A single event type serves two audiences: booking, confirmation and
    cancellation each publish one event to the patient and one to the doctor,
    with the same type and the same configuration. So the audience cannot be
    declared per type — it is read from which FIELD the configuration takes the
    recipient from:

      patient_id  the message is written to the patient ("Your prescription is
                  ready"), so only the appointment's patient will do.
      user_id     either party, since that is how the fan-out addresses them.

    FAIL-OPEN WHEN THE APPOINTMENT IS GONE
    If the appointment cannot be loaded the check is skipped with a warning.
    Events are processed within seconds of publication so this should not
    happen; failing closed would mean a deleted appointment silently killing
    legitimate notifications, which trades a real problem for a hypothetical
    one.
    """
    if appointment_id is None:
        logger.warning(
            "notification_recipient_unverified",
            extra={
                "event_type": event_type,
                "reason": "event carries no appointment_id",
                "recipient_id": recipient_id,
            },
        )
        return

    appointment = await db.get(Appointment, appointment_id)

    if appointment is None:
        logger.warning(
            "notification_recipient_unverified",
            extra={
                "event_type": event_type,
                "reason": "appointment not found",
                "appointment_id": appointment_id,
                "recipient_id": recipient_id,
            },
        )
        return

    allowed = {appointment.patient_id}

    # The doctor is a party too, except where the configuration says the
    # message is addressed to the patient specifically.
    if user_field != "patient_id":
        doctor_user_id = await db.scalar(
            select(Doctor.user_id).where(Doctor.id == appointment.doctor_id)
        )

        if doctor_user_id is not None:
            allowed.add(doctor_user_id)

    if recipient_id in allowed:
        return

    logger.error(
        "notification_recipient_rejected",
        extra={
            "event_type": event_type,
            "recipient_id": recipient_id,
            "appointment_id": appointment_id,
            "clinic_id": appointment.clinic_id,
            "allowed": sorted(allowed),
            "user_field": user_field,
        },
    )

    raise RecipientNotPartyToEvent(
        f"{event_type} addressed to user {recipient_id}, who is neither the "
        f"patient nor the doctor of appointment {appointment_id} "
        f"(clinic {appointment.clinic_id})"
    )


async def handle_notification_event(
    *,
    db: AsyncSession,
    validated,
    event_id,
    event_type,
):

    config = EVENT_NOTIFICATION_CONFIG.get(
        event_type
    )

    if not config:
        return

    # A notification is a message from the clinic to a person. When the system
    # acted on its own — a scheduled job marking an unattended appointment
    # NO_SHOW — there is no message to pass on, and the patient does not need
    # a cron job's verdict on their morning.
    #
    # Everything else about the event still happens. It was published, the
    # audit entry and status history were written by the transition, and the
    # dashboard refresh below still runs: a clinic's board going stale would be
    # a real regression, and it is not a patient notification.
    #
    # Read off the event rather than the event TYPE, so the same status change
    # notifies when a doctor makes it and stays quiet when the scheduler does.
    system_initiated = getattr(validated, "source", None) == EventSource.SYSTEM

    user_id = getattr(
        validated,
        config["user_field"],
        
    )

    appointment_id = getattr(
        validated,
        config["appointment_field"],
        
    )

    # Before anything is sent, and before the message is even built: the
    # recipient has to be someone this event is about.
    await _assert_recipient_is_party_to_event(
        db,
        event_type=event_type,
        user_field=config["user_field"],
        recipient_id=user_id,
        appointment_id=appointment_id,
    )

    if "message_template" in config:

        message = config[
            "message_template"
        ].format(
            **validated.model_dump()
        )

    else:
        message = config["message"]

    if not system_initiated:
        await notify_user(
            db=db,
            user_id=user_id,
            title=config["title"],
            message=message,
            category=config["category"],
            appointment_id=appointment_id,
            event_id=event_id,
        )

    prefs = await get_or_create_preferences(
        db,
        user_id,
    )

    if prefs.realtime_enabled and not system_initiated:
        await send_realtime_notification(
            db=db,
            user_id=user_id,
            payload={
                "version": 1,
                "event": event_type.lower(),
                "correlation_id": validated.correlation_id,
                "data": validated.model_dump(),
                "title": config["title"],
                "message": message,
                "appointment_id": appointment_id,
            },
        )

    if event_type in {
        "APPOINTMENT_CREATED",
        "APPOINTMENT_CONFIRMED",
        "APPOINTMENT_CANCELLED",
        "APPOINTMENT_STATUS_CHANGED",
        "APPOINTMENT_RESCHEDULED",
        "CONSULTATION_STARTED",
        "PATIENT_NEXT_IN_QUEUE",
        "CONSULTATION_COMPLETED",
        "PRESCRIPTION_ISSUED",
        "PRESCRIPTION_REVISED",
        "PAYMENT_REFUNDED",
    }:
        appointment = await db.get(
            Appointment,
            appointment_id,
        )

        if appointment:
            await publish_dashboard_update(
                db=db,
                clinic_id=appointment.clinic_id,
            )