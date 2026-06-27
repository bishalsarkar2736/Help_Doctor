from datetime import (
    date,
    datetime,
    time,
    timedelta,
    timezone
)
from app.core.time import utc_now
from dateutil.relativedelta import relativedelta
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.payment import Payment
from app.models.appointment import Appointment

from app.models.enums.payment_status import (
    PaymentStatus,
)




async def get_revenue_today(
    db: AsyncSession,
    clinic_id: int,
) -> float:
    
    today = utc_now().date()

    start = datetime.combine(
        today,
        time.min,
        tzinfo=timezone.utc,
    )

    end = start + timedelta(days=1)

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
            Payment.status == PaymentStatus.SUCCESS,

            Appointment.clinic_id
            == clinic_id,

            Payment.clinic_id
            == clinic_id,

            Payment.created_at >= start,

            Payment.created_at < end,
        )
    )

    return float(
        result.scalar_one()
    )



async def get_revenue_this_month(
    db: AsyncSession,
    clinic_id: int,
) -> float:
    

    today = utc_now().date()

    month_start = datetime.combine(
        today.replace(day=1),
        time.min,
        tzinfo=timezone.utc,
    )

    next_month = (
        month_start
        + relativedelta(months=1)
    )

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
            Payment.status == PaymentStatus.SUCCESS,

            Appointment.clinic_id
            == clinic_id,

            Payment.clinic_id
            == clinic_id,

            Payment.created_at >= month_start,

            Payment.created_at < next_month,
        )
    )

    return float(
        result.scalar_one()
    )



async def get_monthly_revenue(
    db: AsyncSession,
    clinic_id: int,
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
            ).label("amount"),
        )
        .join(
            Appointment,
            Appointment.id
            == Payment.appointment_id,
        )
        .where(
            Payment.status == PaymentStatus.SUCCESS,

            Appointment.clinic_id
            == clinic_id,

            Payment.clinic_id
            == clinic_id,

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
            "amount": float(row.amount),
        }
        for row in rows
    ]


async def get_total_successful_payments(
    db: AsyncSession,
    clinic_id: int,
) -> int:
    

    result = await db.execute(
        select(
            func.count(
                Payment.id
            )
        )
        .join(
            Appointment,
            Appointment.id
            == Payment.appointment_id,
        )
        .where(
            Payment.status == PaymentStatus.SUCCESS,

            Appointment.clinic_id
            == clinic_id,

            Payment.clinic_id
            == clinic_id,
        )
    )

    return result.scalar_one()


async def get_revenue_analytics(
    db: AsyncSession,
    clinic_id: int,
):

    return {
        "revenue_this_month":
            await get_revenue_this_month(
                db=db,
                clinic_id=clinic_id,
            ),

        "revenue_today":
            await get_revenue_today(
                db=db,
                clinic_id=clinic_id,
            ),

        "total_payments":
            await get_total_successful_payments(
                db=db,
                clinic_id=clinic_id,
            ),

        "monthly_revenue":
            await get_monthly_revenue(
                db=db,
                clinic_id=clinic_id,
            ),
    }