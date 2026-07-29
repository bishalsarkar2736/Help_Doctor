from sqlalchemy.ext.asyncio import AsyncSession

from app.models.appointment import Appointment, AppointmentStatus

from app.services.realtime_dashboard_service import (
    publish_dashboard_update,
    publish_doctor_queue_update,
)

from app.services.queue_notification_service import (
    notify_next_patient,
)

QUEUE_DASHBOARD_STATUSES = {
    AppointmentStatus.CHECKED_IN,
    AppointmentStatus.WAITING,
    AppointmentStatus.IN_CONSULTATION,
    AppointmentStatus.COMPLETED,
}


async def handle_appointment_transition_side_effects(
    *,
    db: AsyncSession,
    appointment: Appointment,
    new_status: AppointmentStatus,
) -> None:
    """
    Execute side effects after an appointment status transition.

    Keep this service free of business rules that modify appointment
    state. It should only trigger external updates such as dashboards,
    queues, notifications, etc.
    """

    #
    # Refresh dashboards
    #
    if new_status in QUEUE_DASHBOARD_STATUSES:

        await publish_dashboard_update(
            db=db,
            clinic_id=appointment.clinic_id,
        )

        await publish_doctor_queue_update(
            db=db,
            doctor_id=appointment.doctor_id,
        )

    #
    # Queue notifications
    #
    if new_status == AppointmentStatus.WAITING:

        await notify_next_patient(
            db=db,
            doctor_id=appointment.doctor_id,
        )

    elif new_status == AppointmentStatus.IN_CONSULTATION:

        # Consultation has started.
        # Notify whoever is now first in the queue.
        await notify_next_patient(
            db=db,
            doctor_id=appointment.doctor_id,
        )

    elif new_status == AppointmentStatus.COMPLETED:

        # Reserved for future side effects.
        pass