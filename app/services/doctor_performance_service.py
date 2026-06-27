from sqlalchemy import case
from sqlalchemy import func
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.appointment import (
    Appointment,
    AppointmentStatus,
)

from app.models.doctor import Doctor
from app.models.payment import Payment
from app.models.user import User
from app.models.enums.payment_status import PaymentStatus


async def get_doctor_performance_scorecard(
    *,
    db: AsyncSession,
    clinic_id: int,
):
    # -----------------------------------------
    # Revenue aggregated per doctor
    # -----------------------------------------

    revenue_subquery = (
        select(
            Appointment.doctor_id.label(
                "doctor_id"
            ),

            func.coalesce(
                func.sum(
                    Payment.amount
                ),
                0,
            ).label(
                "revenue"
            ),
        )
        .join(
            Payment,
            Payment.appointment_id
            == Appointment.id,
        )
        .where(
            Appointment.clinic_id
            == clinic_id,

            Payment.clinic_id
            == clinic_id,

            Payment.status
            == PaymentStatus.SUCCESS,
        )
        .group_by(
            Appointment.doctor_id
        )
        .subquery()
    )

    # -----------------------------------------
    # Main scorecard query
    # -----------------------------------------

    stmt = (
        select(
            Doctor.id.label(
                "doctor_id"
            ),

            User.full_name.label(
                "doctor_name"
            ),

            Doctor.specialization.label(
                "specialization"
            ),

            func.count(
                Appointment.id
            ).label(
                "appointments"
            ),

            func.sum(
                case(
                    (
                        Appointment.status
                        == AppointmentStatus.COMPLETED,
                        1,
                    ),
                    else_=0,
                )
            ).label(
                "completed"
            ),

            func.sum(
                case(
                    (
                        Appointment.status
                        == AppointmentStatus.CANCELLED,
                        1,
                    ),
                    else_=0,
                )
            ).label(
                "cancelled"
            ),

            func.sum(
                case(
                    (
                        Appointment.status
                        == AppointmentStatus.NO_SHOW,
                        1,
                    ),
                    else_=0,
                )
            ).label(
                "no_show"
            ),

            func.coalesce(
                revenue_subquery.c.revenue,
                0,
            ).label(
                "revenue"
            ),
        )

        .join(
            User,
            User.id == Doctor.user_id,
        )

        .outerjoin(
            Appointment,
            (
                Appointment.doctor_id
                == Doctor.id
            )
            &
            (
                Appointment.clinic_id
                == clinic_id
            ),
        )

        .outerjoin(
            revenue_subquery,
            revenue_subquery.c.doctor_id
            == Doctor.id,
        )

        .where(
            Doctor.clinic_id
            == clinic_id
        )

        .group_by(
            Doctor.id,
            User.full_name,
            Doctor.specialization,
            revenue_subquery.c.revenue,
        )

        .order_by(
            func.coalesce(
                revenue_subquery.c.revenue,
                0,
            ).desc()
        )
    )

    result = await db.execute(stmt)

    rows = result.all()

    doctors = []

    for row in rows:

        appointments = (
            row.appointments or 0
        )

        completed = (
            row.completed or 0
        )

        completion_rate = (
            round(
                (
                    completed
                    / appointments
                ) * 100,
                2,
            )
            if appointments
            else 0.0
        )

        doctors.append(
            {
                "doctor_id":
                    row.doctor_id,

                "doctor_name":
                    row.doctor_name,

                "specialization":
                    row.specialization,

                "appointments":
                    appointments,

                "completed_consultations":
                    completed,

                "cancelled":
                    row.cancelled or 0,

                "no_show":
                    row.no_show or 0,

                "completion_rate":
                    completion_rate,

                "revenue":
                    float(
                        row.revenue or 0
                    ),
            }
        )

    return doctors