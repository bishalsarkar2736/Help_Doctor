from app.utils.clinic_time import (
    clinic_timezone,
    clinic_today,
    get_clinic_day_window,
    get_clinic_month_window,
)
from datetime import (
    datetime, 
    time, 
    timedelta, 
    timezone, 
)
from dateutil.relativedelta import relativedelta
from sqlalchemy import func
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.payment import Payment
from app.models.appointment import Appointment

from app.models.enums.payment_status import (
    PaymentStatus,
)


async def get_doctor_revenue_today(
    *,
    db: AsyncSession,
    doctor_id: int,
    clinic_id : int,
) -> float:
    
    tz_name = await clinic_timezone(db, clinic_id)

    start, end = get_clinic_day_window(tz_name, clinic_today(tz_name))

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
            Appointment.doctor_id== doctor_id,
            Appointment.clinic_id== clinic_id,
            Payment.clinic_id== clinic_id,

            Payment.status == PaymentStatus.SUCCESS,

            Payment.created_at >= start,
            Payment.created_at < end,
        )
    )

    return float(
        result.scalar_one()
    )



async def get_doctor_revenue_this_month(
    *,
    db: AsyncSession,
    doctor_id: int,
    clinic_id : int,
) -> float:
    
  

    tz_name = await clinic_timezone(db, clinic_id)

    month_start, next_month = get_clinic_month_window(
        tz_name, clinic_today(tz_name)
    )

    next_month = month_start + relativedelta(months=1)

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
            Appointment.doctor_id== doctor_id,
            Appointment.clinic_id== clinic_id,
            Payment.clinic_id== clinic_id,

            Payment.status == PaymentStatus.SUCCESS,

            Payment.created_at >= month_start,
            Payment.created_at < next_month,
        )
    )

    return float(
        result.scalar_one()
    )


