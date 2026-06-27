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
from app.utils.date_ranges import (
    get_month_range,
    get_today_range,
)



async def get_total_count(
    db: AsyncSession,
    model,
    clinic_id: int,
) -> int:

    result = await db.execute(
        select(
            func.count(model.id)
        )
        .where(
            model.clinic_id == clinic_id
        )
    )

    return result.scalar_one()


async def get_today_count(
    db: AsyncSession,
    model,
    date_column,
    clinic_id: int,
) -> int:

    start, end = get_today_range()

    result = await db.execute(
        select(
            func.count(model.id)
        ).where(
            model.clinic_id == clinic_id,
            date_column >= start,
            date_column < end,
        )
    )

    return result.scalar_one()


async def get_month_count(
    db: AsyncSession,
    model,
    date_column,
    clinic_id: int,
) -> int:

    start, end = get_month_range()

    result = await db.execute(
        select(
            func.count(model.id)
        ).where(
            model.clinic_id == clinic_id,
            date_column >= start,
            date_column < end,
        )
    )

    return result.scalar_one()


async def get_clinic_analytics(
    db: AsyncSession,
    clinic_id: int,
):

    return {

        "total_appointments":
            await get_total_count(
                db,
                Appointment,
                clinic_id,
            ),

        "appointments_this_month":
            await get_month_count(
                db,
                Appointment,
                Appointment.created_at,
                clinic_id,
            ),

        "appointments_today":
            await get_today_count(
                db,
                Appointment,
                Appointment.created_at,
                clinic_id,
            ),

        "total_prescriptions":
            await get_total_count(
                db,
                Prescription,
                clinic_id,
            ),

        "prescriptions_this_month":
            await get_month_count(
                db,
                Prescription,
                Prescription.created_at,
                clinic_id,
            ),

        "prescriptions_today":
            await get_today_count(
                db,
                Prescription,
                Prescription.created_at,
                clinic_id,
            ),

        "total_payments":
            await get_total_count(
                db,
                Payment,
                clinic_id,
            ),

        "payments_this_month":
            await get_month_count(
                db,
                Payment,
                Payment.created_at,
                clinic_id,
            ),

        "payments_today":
            await get_today_count(
                db,
                Payment,
                Payment.created_at,
                clinic_id,
            ),

        "medicine_ai_requests":
            await get_total_count(
                db,
                MedicineAILog,
                clinic_id,
            ),
    }