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
from app.services.notification_preference_service import (
    get_or_create_preferences,
)

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

    user_id = getattr(
        validated,
        config["user_field"],
        
    )

    appointment_id = getattr(
        validated,
        config["appointment_field"],
        
    )

    if "message_template" in config:

        message = config[
            "message_template"
        ].format(
            **validated.model_dump()
        )

    else:
        message = config["message"]

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

    if prefs.realtime_enabled:
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