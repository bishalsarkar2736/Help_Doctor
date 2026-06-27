from datetime import date

from dateutil.relativedelta import relativedelta

from sqlalchemy import func
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.payment import Payment
from app.models.appointment import Appointment



async def get_doctor_monthly_revenue(
    *,
    db: AsyncSession,
    doctor_id: int,
    clinic_id : int,
    months: int = 12,
):

    start_date = (
        date.today().replace(day=1)
        - relativedelta(months=months - 1)
    )

    result = await db.execute(
        select(
            func.to_char(
                Payment.created_at,
                "YYYY-MM",
            ).label("month"),

            func.coalesce(
                func.sum(
                    Payment.amount
                ),
                0,
            ).label("revenue"),
        )
        .join(
            Appointment,
            Appointment.id
            == Payment.appointment_id,
        )
        .where(
            Appointment.doctor_id
            == doctor_id,

            Appointment.clinic_id
            == clinic_id,

            Payment.clinic_id
            == clinic_id,

            Payment.status
            == "SUCCESS",

            Payment.created_at
            >= start_date,
        )
        .group_by("month")
        .order_by("month")
    )

    rows = result.all()

    return [
        {
            "month": row.month,
            "revenue": float(
                row.revenue
            ),
        }
        for row in rows
    ]