from sqlalchemy import func
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.models.doctor import Doctor
from app.models.payment import Payment
from app.models.appointment import Appointment

from app.services.clinic_context_service import (
    get_current_clinic,
)


async def get_top_doctors(
    *,
    db: AsyncSession,
    limit: int = 5,
):
    clinic = await get_current_clinic(db)

    result = await db.execute(
        select(
            Doctor.id.label(
                "doctor_id"
            ),

            User.full_name.label(
                "doctor_name"
            ),

            Doctor.specialization,

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
                "successful_payments"
            ),
        )

        .join(
            User,
            User.id
            == Doctor.user_id,
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
            == clinic.id,

            Appointment.clinic_id
            == clinic.id,

            Payment.clinic_id
            == clinic.id,

            Payment.status
            == "SUCCESS",
        )

        .group_by(
            Doctor.id,
            User.full_name,
            Doctor.specialization,
        )

        .order_by(
            func.sum(
                Payment.amount
            ).desc()
        )

        .limit(limit)
    )

    rows = result.all()

    return {
        "doctors": [
            {
                "doctor_id": row.doctor_id,
                "doctor_name": row.doctor_name,
                "specialization": row.specialization,
                "revenue": float(
                    row.revenue
                ),
                "successful_payments":
                    row.successful_payments,
            }
            for row in rows
        ]
    }