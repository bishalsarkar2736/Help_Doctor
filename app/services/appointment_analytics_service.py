from datetime import date

from sqlalchemy import (
    func,
    select,
)

from sqlalchemy.ext.asyncio import (
    AsyncSession,
)

from app.models.appointment import (
    Appointment,
    AppointmentStatus,
)

from app.services.clinic_context_service import (
    get_current_clinic,
)


today = date.today()


async def get_status_total(
    db: AsyncSession,
    status: AppointmentStatus,
    clinic_id: int,
) -> int:

    result = await db.execute(
        select(
            func.count(
                Appointment.id
            )
        ).where(
            Appointment.status == status,
            Appointment.clinic_id
            == clinic_id,
        )
    )

    return result.scalar_one()


async def get_status_this_month(
    db: AsyncSession,
    status: AppointmentStatus,
    clinic_id: int,
) -> int:

    result = await db.execute(
        select(
            func.count(
                Appointment.id
            )
        ).where(
            Appointment.status == status,
            Appointment.clinic_id
            == clinic_id,

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
    clinic_id: int,
) -> int:

    result = await db.execute(
        select(
            func.count(
                Appointment.id
            )
        ).where(
            Appointment.clinic_id
            == clinic_id,

            Appointment.confirmed_at.is_not(
                None
            ),

            func.extract(
                "month",
                Appointment.confirmed_at,
            ) == today.month,

            func.extract(
                "year",
                Appointment.confirmed_at,
            ) == today.year,
        )
    )

    return result.scalar_one()


async def get_completed_this_month(
    db: AsyncSession,
    clinic_id: int,
) -> int:

    result = await db.execute(
        select(
            func.count(
                Appointment.id
            )
        ).where(
            Appointment.clinic_id
            == clinic_id,

            Appointment.completed_at.is_not(
                None
            ),

            func.extract(
                "month",
                Appointment.completed_at,
            ) == today.month,

            func.extract(
                "year",
                Appointment.completed_at,
            ) == today.year,
        )
    )

    return result.scalar_one()


async def get_cancelled_this_month(
    db: AsyncSession,
    clinic_id: int,
) -> int:

    result = await db.execute(
        select(
            func.count(
                Appointment.id
            )
        ).where(
            Appointment.clinic_id
            == clinic_id,

            Appointment.cancelled_at.is_not(
                None
            ),

            func.extract(
                "month",
                Appointment.cancelled_at,
            ) == today.month,

            func.extract(
                "year",
                Appointment.cancelled_at,
            ) == today.year,
        )
    )

    return result.scalar_one()


async def get_appointment_analytics(
    db: AsyncSession,
):

    clinic = await get_current_clinic(
        db
    )

    return {

        "scheduled_total":
            await get_status_total(
                db,
                AppointmentStatus.SCHEDULED,
                clinic.id,
            ),

        "scheduled_this_month":
            await get_status_this_month(
                db,
                AppointmentStatus.SCHEDULED,
                clinic.id,
            ),

        "confirmed_total":
            await get_status_total(
                db,
                AppointmentStatus.CONFIRMED,
                clinic.id,
            ),

        "confirmed_this_month":
            await get_status_this_month(
                db,
                AppointmentStatus.CONFIRMED,
                clinic.id,
            ),

        "completed_total":
            await get_status_total(
                db,
                AppointmentStatus.COMPLETED,
                clinic.id,
            ),

        "completed_this_month":
            await get_status_this_month(
                db,
                AppointmentStatus.COMPLETED,
                clinic.id,
            ),

        "cancelled_total":
            await get_status_total(
                db,
                AppointmentStatus.CANCELLED,
                clinic.id,
            ),

        "cancelled_this_month":
            await get_status_this_month(
                db,
                AppointmentStatus.CANCELLED,
                clinic.id,
            ),

        "no_show_total":
            await get_status_total(
                db,
                AppointmentStatus.NO_SHOW,
                clinic.id,
            ),

        "no_show_this_month":
            await get_status_this_month(
                db,
                AppointmentStatus.NO_SHOW,
                clinic.id,
            ),

        "in_consultation_total":
            await get_status_total(
                db,
                AppointmentStatus.IN_CONSULTATION,
                clinic.id,
            ),

        "confirmed_by_timestamp_this_month":
            await get_confirmed_this_month(
                db,
                clinic.id,
            ),

        "completed_by_timestamp_this_month":
            await get_completed_this_month(
                db,
                clinic.id,
            ),

        "cancelled_by_timestamp_this_month":
            await get_cancelled_this_month(
                db,
                clinic.id,
            ),
    }

