from app.schemas.appointment import (
    AppointmentDetailOut,
    TimeSlotOut,
)

from app.schemas.doctor import DoctorPublic
from app.schemas.public_user import UserPublic


def to_appointment_detail(appointment):

    return AppointmentDetailOut(
        id=appointment.id,

        doctor_id=appointment.doctor_id,
        patient_id=appointment.patient_id,

        scheduled_at=appointment.scheduled_at,
        status=appointment.status.value,

        notes=appointment.notes,

        cancel_reason=appointment.cancel_reason,

        cancelled_at=appointment.cancelled_at,
        confirmed_at=appointment.confirmed_at,
        completed_at=appointment.completed_at,

        reminder_sent=appointment.reminder_sent,
        version=appointment.version,

        created_at=appointment.created_at,

        time_slot=(
            TimeSlotOut(
                starts_at=appointment.time_range.lower,
                ends_at=appointment.time_range.upper,
            )
            if appointment.time_range
            else None
        ),

        doctor=DoctorPublic.model_validate(
            appointment.doctor,
            from_attributes=True,
        ),

        patient=UserPublic.model_validate(
            appointment.patient,
            from_attributes=True,
        ),
    )