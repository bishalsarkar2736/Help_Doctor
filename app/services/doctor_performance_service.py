from sqlalchemy import func
from sqlalchemy import case
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.appointment import (
    Appointment,
    AppointmentStatus,
)

from app.models.payment import Payment
from app.models.doctor import Doctor
from app.models.user import User

from app.services.clinic_context_service import (
    get_current_clinic,
)


async def get_doctor_performance_scorecard(
    *,
    db: AsyncSession,
):
    clinic = await get_current_clinic(db)

    stmt = (
        select(
            Doctor.id.label("doctor_id"),

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
                func.sum(
                    case(
                        (
                            Payment.status
                            == "SUCCESS",
                            Payment.amount,
                        ),
                        else_=0,
                    )
                ),
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
            Appointment.doctor_id
            == Doctor.id,
        )

        .outerjoin(
            Payment,
            Payment.appointment_id
            == Appointment.id,
        )

        .where(
            Doctor.clinic_id
            == clinic.id
        )

        .group_by(
            Doctor.id,
            User.full_name,
            Doctor.specialization,
        )

        .order_by(
            func.coalesce(
                func.sum(
                    case(
                        (
                            Payment.status
                            == "SUCCESS",
                            Payment.amount,
                        ),
                        else_=0,
                    )
                ),
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