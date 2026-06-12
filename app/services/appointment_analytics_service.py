from datetime import date

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.appointment import (
    Appointment,
    AppointmentStatus,
)

today = date.today()


async def get_status_total(
    db: AsyncSession,
    status: AppointmentStatus,
) -> int:

    result = await db.execute(
        select(
            func.count(
                Appointment.id
            )
        ).where(
            Appointment.status == status
        )
    )

    return result.scalar_one()


async def get_status_this_month(
    db: AsyncSession,
    status: AppointmentStatus,
) -> int:

    result = await db.execute(
        select(
            func.count(
                Appointment.id
            )
        ).where(
            Appointment.status == status,
            func.extract(
                "month",
                Appointment.created_at,
            ) == today.month,
            func.extract(
                "year",
                Appointment.created_at,
            ) == today.year,
        )
    )

    return result.scalar_one()


async def get_confirmed_this_month(
    db: AsyncSession,
) -> int:

    result = await db.execute(
        select(
            func.count(
                Appointment.id
            )
        ).where(
            Appointment.confirmed_at.is_not(
                None
            ),
            func.extract(
                "month",
                Appointment.confirmed_at,
            )
            == today.month,
            func.extract(
                "year",
                Appointment.confirmed_at,
            )
            == today.year,
        )
    )

    return result.scalar_one()


async def get_completed_this_month(
    db: AsyncSession,
) -> int:

    result = await db.execute(
        select(
            func.count(
                Appointment.id
            )
        ).where(
            Appointment.completed_at.is_not(
                None
            ),
            func.extract(
                "month",
                Appointment.completed_at,
            )
            == today.month,
            func.extract(
                "year",
                Appointment.completed_at,
            )
            == today.year,
        )
    )

    return result.scalar_one()


async def get_cancelled_this_month(
    db: AsyncSession,
) -> int:

    result = await db.execute(
        select(
            func.count(
                Appointment.id
            )
        ).where(
            Appointment.cancelled_at.is_not(
                None
            ),
            func.extract(
                "month",
                Appointment.cancelled_at,
            )
            == today.month,
            func.extract(
                "year",
                Appointment.cancelled_at,
            )
            == today.year,
        )
    )

    return result.scalar_one()



async def get_appointment_analytics(
    db: AsyncSession,
):

    return {

        "scheduled_total":
            await get_status_total(
                db,
                AppointmentStatus.SCHEDULED,
            ),

        "scheduled_this_month":
            await get_status_this_month(
                db,
                AppointmentStatus.SCHEDULED,
            ),

        "confirmed_total":
            await get_status_total(
                db,
                AppointmentStatus.CONFIRMED,
            ),

        "confirmed_this_month":
            await get_status_this_month(
                db,
            ),

        "completed_total":
            await get_status_total(
                db,
                AppointmentStatus.COMPLETED,
            ),

        "completed_this_month":
            await get_status_this_month(
                db,
            ),

        "cancelled_total":
            await get_status_total(
                db,
                AppointmentStatus.CANCELLED,
            ),

        "cancelled_this_month":
            await get_status_this_month(
                db,
            ),

        "no_show_total":
            await get_status_total(
                db,
                AppointmentStatus.NO_SHOW,
            ),

        "no_show_this_month":
            await get_status_this_month(
                db,
                AppointmentStatus.NO_SHOW,
            ),

        "in_consultation_total":
            await get_status_total(
                db,
                AppointmentStatus.IN_CONSULTATION,
            ),
    }