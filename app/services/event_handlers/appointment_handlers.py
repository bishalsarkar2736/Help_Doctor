# from sqlalchemy.ext.asyncio import AsyncSession

# from app.services.notification_service import (
#     notify_user,
# )

# from app.schemas.event import (
#     AppointmentCreatedEvent,
#     AppointmentConfirmedEvent,
#     AppointmentCancelledEvent,
#     AppointmentRescheduledEvent,
#     AppointmentRescheduleRequestEvent,
#     AppointmentStatusChangedEvent,
# )


# async def handle_appointment_status_changed(
#     *,
#     db: AsyncSession,
#     validated: AppointmentStatusChangedEvent,
#     event_id,
# ):

#     await notify_user(
#         db=db,
#         user_id=validated.patient_id,
#         title="Appointment Update",
#         message=f"Your appointment status changed to {validated.new_status}",
#         appointment_id=validated.appointment_id,
#         event_id=event_id,
#     )


# async def handle_appointment_created(
#     *,
#     db: AsyncSession,
#     validated: AppointmentCreatedEvent,
#     event_id,
# ):

#     await notify_user(
#         db=db,
#         user_id=validated.user_id,
#         title="Appointment Created",
#         message="A new appointment has been booked",
#         appointment_id=validated.appointment_id,
#         event_id=event_id,
#     )


# async def handle_appointment_confirmed(
#     *,
#     db: AsyncSession,
#     validated: AppointmentConfirmedEvent,
#     event_id,
# ):

#     await notify_user(
#         db=db,
#         user_id=validated.user_id,
#         title="Appointment Confirmed",
#         message="Your appointment has been confirmed",
#         appointment_id=validated.appointment_id,
#         event_id=event_id,
#     )


# async def handle_appointment_cancelled(
#     *,
#     db: AsyncSession,
#     validated: AppointmentCancelledEvent,
#     event_id,
# ):

#     await notify_user(
#         db=db,
#         user_id=validated.user_id,
#         title="Appointment Cancelled",
#         message="Your appointment has been cancelled",
#         appointment_id=validated.appointment_id,
#         event_id=event_id,
#     )


# async def handle_appointment_rescheduled(
#     *,
#     db: AsyncSession,
#     validated: AppointmentRescheduledEvent,
#     event_id,
# ):

#     await notify_user(
#         db=db,
#         user_id=validated.user_id,
#         title="Appointment Rescheduled",
#         message="Your appointment has been rescheduled",
#         appointment_id=validated.appointment_id,
#         event_id=event_id,
#     )


# async def handle_appointment_reschedule_request(
#     *,
#     db: AsyncSession,
#     validated: AppointmentRescheduleRequestEvent,
#     event_id,
# ):

#     await notify_user(
#         db=db,
#         user_id=validated.user_id,
#         title="Reschedule Request",
#         message="A patient requested to reschedule an appointment",
#         appointment_id=validated.appointment_id,
#         event_id=event_id,
#     )