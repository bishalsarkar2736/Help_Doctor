from sqlalchemy import func
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.payment import Payment
from app.models.appointment import Appointment
from app.models.doctor import Doctor


async def get_revenue_by_specialization(
    *,
    db: AsyncSession,
    clinic_id : int,
):


    result = await db.execute(
        select(
            Doctor.specialization.label(
                "specialization"
            ),

            func.coalesce(
                func.sum(
                    Payment.amount
                ),
                0,
            ).label(
                "revenue"
            ),

            func.count(
                Payment.id
            ).label(
                "payments"
            ),
        )
        .join(
            Appointment,
            Appointment.doctor_id
            == Doctor.id,
        )
        .join(
            Payment,
            Payment.appointment_id
            == Appointment.id,
        )
        .where(
            Doctor.clinic_id
            == clinic_id,

            Appointment.clinic_id
            == clinic_id,

            Payment.clinic_id
            == clinic_id,

            Payment.status
            == "SUCCESS",
        )
        .group_by(
            Doctor.specialization
        )
        .order_by(
            func.sum(
                Payment.amount
            ).desc()
        )
    )

    rows = result.all()

    return [
        {
            "specialization":
                row.specialization,

            "revenue":
                float(row.revenue),

            "payments":
                row.payments,
        }
        for row in rows
    ]