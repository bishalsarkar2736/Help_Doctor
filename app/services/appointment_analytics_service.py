
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession


from app.models.appointment import (
    Appointment,
    AppointmentStatus,
)
from app.utils.date_ranges import (
    get_month_range,
)


async def get_appointment_analytics(
    *,
    db: AsyncSession,
    clinic_id: int,
):
    month_start, next_month = (
        get_month_range()
    )

    stmt = select(

        # ----------------------------------
        # SCHEDULED
        # ----------------------------------

        func.count(Appointment.id)
        .filter(
            Appointment.status
            == AppointmentStatus.SCHEDULED
        )
        .label("scheduled_total"),

        func.count(Appointment.id)
        .filter(
            Appointment.status
            == AppointmentStatus.SCHEDULED,

            Appointment.created_at
            >= month_start,

            Appointment.created_at
            < next_month,
        )
        .label("scheduled_this_month"),

        # ----------------------------------
        # CONFIRMED
        # ----------------------------------

        func.count(Appointment.id)
        .filter(
            Appointment.status
            == AppointmentStatus.CONFIRMED
        )
        .label("confirmed_total"),

        func.count(Appointment.id)
        .filter(
            Appointment.status
            == AppointmentStatus.CONFIRMED,

            Appointment.created_at
            >= month_start,

            Appointment.created_at
            < next_month,
        )
        .label("confirmed_this_month"),

        # ----------------------------------
        # COMPLETED
        # ----------------------------------

        func.count(Appointment.id)
        .filter(
            Appointment.status
            == AppointmentStatus.COMPLETED
        )
        .label("completed_total"),

        func.count(Appointment.id)
        .filter(
            Appointment.status
            == AppointmentStatus.COMPLETED,

            Appointment.created_at
            >= month_start,

            Appointment.created_at
            < next_month,
        )
        .label("completed_this_month"),

        # ----------------------------------
        # CANCELLED
        # ----------------------------------

        func.count(Appointment.id)
        .filter(
            Appointment.status
            == AppointmentStatus.CANCELLED
        )
        .label("cancelled_total"),

        func.count(Appointment.id)
        .filter(
            Appointment.status
            == AppointmentStatus.CANCELLED,

            Appointment.created_at
            >= month_start,

            Appointment.created_at
            < next_month,
        )
        .label("cancelled_this_month"),

        # ----------------------------------
        # NO SHOW
        # ----------------------------------

        func.count(Appointment.id)
        .filter(
            Appointment.status
            == AppointmentStatus.NO_SHOW
        )
        .label("no_show_total"),

        func.count(Appointment.id)
        .filter(
            Appointment.status
            == AppointmentStatus.NO_SHOW,

            Appointment.created_at
            >= month_start,

            Appointment.created_at
            < next_month,
        )
        .label("no_show_this_month"),

        # ----------------------------------
        # IN CONSULTATION
        # ----------------------------------

        func.count(Appointment.id)
        .filter(
            Appointment.status
            == AppointmentStatus.IN_CONSULTATION
        )
        .label("in_consultation_total"),

        # ----------------------------------
        # TIMESTAMP-BASED METRICS
        # ----------------------------------

        func.count(Appointment.id)
        .filter(
            Appointment.confirmed_at
            >= month_start,

            Appointment.confirmed_at
            < next_month,
        )
        .label(
            "confirmed_by_timestamp_this_month"
        ),

        func.count(Appointment.id)
        .filter(
            Appointment.completed_at
            >= month_start,

            Appointment.completed_at
            < next_month,
        )
        .label(
            "completed_by_timestamp_this_month"
        ),

        func.count(Appointment.id)
        .filter(
            Appointment.cancelled_at
            >= month_start,

            Appointment.cancelled_at
            < next_month,
        )
        .label(
            "cancelled_by_timestamp_this_month"
        ),
    ).where(
        Appointment.clinic_id
        == clinic_id
    )

    result = await db.execute(stmt)

    row = result.one()

    return {
        "scheduled_total":
            row.scheduled_total or 0,

        "scheduled_this_month":
            row.scheduled_this_month or 0,

        "confirmed_total":
            row.confirmed_total or 0,

        "confirmed_this_month":
            row.confirmed_this_month or 0,

        "completed_total":
            row.completed_total or 0,

        "completed_this_month":
            row.completed_this_month or 0,

        "cancelled_total":
            row.cancelled_total or 0,

        "cancelled_this_month":
            row.cancelled_this_month or 0,

        "no_show_total":
            row.no_show_total or 0,

        "no_show_this_month":
            row.no_show_this_month or 0,

        "in_consultation_total":
            row.in_consultation_total or 0,

        "confirmed_by_timestamp_this_month":
            row.confirmed_by_timestamp_this_month or 0,

        "completed_by_timestamp_this_month":
            row.completed_by_timestamp_this_month or 0,

        "cancelled_by_timestamp_this_month":
            row.cancelled_by_timestamp_this_month or 0,
    }