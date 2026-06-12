from datetime import (
    date,
    datetime,
    timedelta,
)

from sqlalchemy import (
    func,
    select,
)

from sqlalchemy.ext.asyncio import (
    AsyncSession,
)

from app.models.appointment import (
    Appointment,
)

from app.models.prescription import (
    Prescription,
)

from app.models.payment import (
    Payment,
)

from app.models.medicine_ai_log import (
    MedicineAILog,
)


def get_today_range():

    start = datetime.combine(
        date.today(),
        datetime.min.time(),
    )

    end = start + timedelta(days=1)

    return start, end


def get_month_range():

    today = date.today()

    start = datetime(
        today.year,
        today.month,
        1,
    )

    if today.month == 12:

        end = datetime(
            today.year + 1,
            1,
            1,
        )

    else:

        end = datetime(
            today.year,
            today.month + 1,
            1,
        )

    return start, end


async def get_total_count(
    db: AsyncSession,
    model,
) -> int:

    result = await db.execute(
        select(
            func.count(model.id)
        )
    )

    return result.scalar_one()


async def get_today_count(
    db: AsyncSession,
    model,
    date_column,
) -> int:

    start, end = get_today_range()

    result = await db.execute(
        select(
            func.count(model.id)
        ).where(
            date_column >= start,
            date_column < end,
        )
    )

    return result.scalar_one()


async def get_month_count(
    db: AsyncSession,
    model,
    date_column,
) -> int:

    start, end = get_month_range()

    result = await db.execute(
        select(
            func.count(model.id)
        ).where(
            date_column >= start,
            date_column < end,
        )
    )

    return result.scalar_one()



async def get_clinic_analytics(
    db: AsyncSession,
):

    return {

        "total_appointments":
            await get_total_count(
                db,
                Appointment,
            ),

        "appointments_this_month":
            await get_month_count(
                db,
                Appointment,
                Appointment.created_at,
            ),

        "appointments_today":
            await get_today_count(
                db,
                Appointment,
                Appointment.created_at,
            ),

        "total_prescriptions":
            await get_total_count(
                db,
                Prescription,
            ),

        "prescriptions_this_month":
            await get_month_count(
                db,
                Prescription,
                Prescription.created_at,
            ),

        "prescriptions_today":
            await get_today_count(
                db,
                Prescription,
                Prescription.created_at,
            ),

        "total_payments":
            await get_total_count(
                db,
                Payment,
            ),

        "payments_this_month":
            await get_month_count(
                db,
                Payment,
                Payment.created_at,
            ),

        "payments_today":
            await get_today_count(
                db,
                Payment,
                Payment.created_at,
            ),

        "medicine_ai_requests":
            await get_total_count(
                db,
                MedicineAILog,
            ),
    }