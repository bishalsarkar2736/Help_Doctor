from datetime import date

from sqlalchemy import func
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.payment import Payment
from app.models.appointment import Appointment,AppointmentStatus


async def get_doctor_revenue_today(
    *,
    db: AsyncSession,
    doctor_id: int,
) -> float:

    today = date.today()

    result = await db.execute(
        select(
            func.coalesce(
                func.sum(
                    Payment.amount
                ),
                0,
            )
        )
        .join(
            Appointment,
            Appointment.id
            == Payment.appointment_id,
        )
        .where(
            Appointment.doctor_id
            == doctor_id,

            Payment.status
            == "SUCCESS",

            func.date(
                Payment.created_at
            )
            == today,
        )
    )

    return float(
        result.scalar_one()
    )



async def get_doctor_revenue_this_month(
    *,
    db: AsyncSession,
    doctor_id: int,
) -> float:

    today = date.today()

    result = await db.execute(
        select(
            func.coalesce(
                func.sum(
                    Payment.amount
                ),
                0,
            )
        )
        .join(
            Appointment,
            Appointment.id
            == Payment.appointment_id,
        )
        .where(
            Appointment.doctor_id
            == doctor_id,

            Payment.status
            == "SUCCESS",

            func.extract(
                "month",
                Payment.created_at,
            )
            == today.month,

            func.extract(
                "year",
                Payment.created_at,
            )
            == today.year,
        )
    )

    return float(
        result.scalar_one()
    )


async def get_completion_rate(
    *,
    db: AsyncSession,
    doctor_id: int,
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