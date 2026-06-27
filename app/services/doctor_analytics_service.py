from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.appointment import Appointment,AppointmentStatus
from app.models.doctor import Doctor
from app.models.user import User




async def get_top_doctors_by_appointments(
    *,
    db: AsyncSession,
    clinic_id : int,
):


    result = await db.execute(
        select(
            Doctor.id.label("doctor_id"),

            User.full_name.label(
                "doctor_name"
            ),

            Doctor.specialization.label(
                "specialization"
            ),

            func.count(
                Appointment.id
            ).label(
                "appointment_count"
            ),
        )
        .join(
            User,
            User.id == Doctor.user_id,
        )
        .join(
            Appointment,
            Appointment.doctor_id == Doctor.id,
        )
        .where(
            Doctor.clinic_id == clinic_id,
            Appointment.clinic_id == clinic_id,
        )
        .group_by(
            Doctor.id,
            User.full_name,
            Doctor.specialization,
        )
        .order_by(
            func.count(
                Appointment.id
            ).desc()
        )
    )

    rows = result.all()

    return [
        {
            "doctor_id": row.doctor_id,
            "doctor_name": row.doctor_name,
            "specialization": row.specialization,
            "appointment_count": row.appointment_count,
        }
        for row in rows
    ]



async def get_top_doctors_by_completed_consultations(
    *,
    db: AsyncSession,
    clinic_id : int,
):

    result = await db.execute(
        select(
            Doctor.id.label("doctor_id"),

            User.full_name.label(
                "doctor_name"
            ),

            Doctor.specialization.label(
                "specialization"
            ),

            func.count(
                Appointment.id
            ).label(
                "completed_consultations"
            ),
        )

        .join(
            User,
            User.id == Doctor.user_id,
        )

        .join(
            Appointment,
            Appointment.doctor_id
            == Doctor.id,
        )

        .where(
            Doctor.clinic_id
            == clinic_id,

            Appointment.clinic_id
            == clinic_id,

            Appointment.status
            == AppointmentStatus.COMPLETED,
        )

        .group_by(
            Doctor.id,
            User.full_name,
            Doctor.specialization,
        )

        .order_by(
            func.count(
                Appointment.id
            ).desc()
        )
    )

    rows = result.all()

    return [
        {
            "doctor_id": row.doctor_id,
            "doctor_name": row.doctor_name,
            "specialization": row.specialization,
            "completed_consultations": (
                row.completed_consultations
            ),
        }
        for row in rows
    ]


async def get_completion_rate(
    *,
    db: AsyncSession,
    doctor_id: int,
    clinic_id : int,
) -> float:
    


    completed_result = await db.execute(
        select(
            func.count(
                Appointment.id
            )
        )
        .where(
            Appointment.doctor_id
            == doctor_id,

            Appointment.clinic_id
            == clinic_id,

            Appointment.status
            == AppointmentStatus.COMPLETED,
        )
    )

    completed = (
        completed_result.scalar_one()
    )

    cancelled_result = await db.execute(
        select(
            func.count(
                Appointment.id
            )
        )
        .where(
            Appointment.doctor_id
            == doctor_id,

            Appointment.clinic_id
            == clinic_id,

            Appointment.status
            == AppointmentStatus.CANCELLED,
        )
    )

    cancelled = (
        cancelled_result.scalar_one()
    )

    total = completed + cancelled

    if total == 0:
        return 0.0

    return round(
        (completed / total) * 100,
        2,
    )