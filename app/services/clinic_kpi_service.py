from sqlalchemy import func
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.appointment import Appointment,AppointmentStatus
from app.models.patient import Patient
from app.models.payment import Payment
from datetime import date

from app.schemas.clinic_kpi_schema import (
    ClinicKPIResponse,
)
from app.models.enums.payment_status import (
    PaymentStatus,
)



async def get_total_patients(
    *,
    db: AsyncSession,
    clinic_id: int,
) -> int:


    result = await db.execute(
        select(
            func.count(
                Patient.id
            )
        )
        .where(
            Patient.clinic_id
            == clinic_id
        )
    )

    return result.scalar_one()


async def get_total_appointments(
    *,
    db: AsyncSession,
    clinic_id: int,
) -> int:

    result = await db.execute(
        select(
            func.count(
                Appointment.id
            )
        )
        .where(
            Appointment.clinic_id
            == clinic_id
        )
    )

    return result.scalar_one()


async def get_total_revenue(
    db: AsyncSession,
    clinic_id: int,
) -> float:
    

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
        )

    )

    return float(
        result.scalar_one()
    )


async def get_conversion_rate(
    *,
    db: AsyncSession,
    clinic_id: int,
) -> float:

    total_result = await db.execute(
        select(
            func.count(
                Appointment.id
            )
        )
        .where(
            Appointment.clinic_id
            == clinic_id
        )
    )

    total_appointments = (
        total_result.scalar_one()
    )

    if total_appointments == 0:
        return 0.0

    completed_result = await db.execute(
        select(
            func.count(
                Appointment.id
            )
        )
        .where(
            Appointment.clinic_id
            == clinic_id,
            Appointment.status
            == AppointmentStatus.COMPLETED,
        )
    )

    completed = (
        completed_result.scalar_one()
    )

    return round(
        (completed / total_appointments)
        * 100,
        2,
    )


async def get_completion_rate_total_clinic(
    *,
    db: AsyncSession,
    clinic_id: int,
) -> float:

    completed_result = await db.execute(
        select(
            func.count(
                Appointment.id
            )
        )
        .where(
            Appointment.clinic_id
            == clinic_id,

            Appointment.status
            == AppointmentStatus.COMPLETED,
        )
    )

    completed = (
        completed_result.scalar_one()
    )

    cancelled_result = await db.execute(
        select(
            func.count(
                Appointment.id
            )
        )
        .where(
            Appointment.clinic_id
            == clinic_id,

            Appointment.status
            == AppointmentStatus.CANCELLED,
        )
    )

    cancelled = (
        cancelled_result.scalar_one()
    )

    total_finished = (
        completed + cancelled
    )

    if total_finished == 0:
        return 0.0

    return round(
        (
            completed
            / total_finished
        ) * 100,
        2,
    )


async def get_patients_today(
    *,
    db: AsyncSession,
    clinic_id: int,
) -> int:


    today = date.today()

    result = await db.execute(
        select(
            func.count(Patient.id)
        )
        .where(
            Patient.clinic_id == clinic_id,
            func.date(
                Patient.created_at
            ) == today,
        )
    )

    return result.scalar_one()



async def get_patients_this_month(
    *,
    db: AsyncSession,
    clinic_id: int,
) -> int:

    today = date.today()

    result = await db.execute(
        select(
            func.count(Patient.id)
        )
        .where(
            Patient.clinic_id == clinic_id,

            func.extract(
                "month",
                Patient.created_at,
            ) == today.month,

            func.extract(
                "year",
                Patient.created_at,
            ) == today.year,
        )
    )

    return result.scalar_one()


async def get_appointments_today(
    *,
    db: AsyncSession,
    clinic_id: int,
) -> int:


    today = date.today()

    result = await db.execute(
        select(
            func.count(
                Appointment.id
            )
        )
        .where(
            Appointment.clinic_id
            == clinic_id,

            func.date(
                Appointment.created_at
            )
            == today,
        )
    )

    return result.scalar_one()



async def get_appointments_this_month(
    *,
    db: AsyncSession,
    clinic_id: int,
) -> int:

    today = date.today()

    result = await db.execute(
        select(
            func.count(
                Appointment.id
            )
        )
        .where(
            Appointment.clinic_id
            == clinic_id,

            func.extract(
                "month",
                Appointment.created_at,
            )
            == today.month,

            func.extract(
                "year",
                Appointment.created_at,
            )
            == today.year,
        )
    )

    return result.scalar_one()



async def get_average_revenue_per_appointment(
    *,
    db: AsyncSession,
    clinic_id: int,
) -> float:


    revenue_result = await db.execute(
        select(
            func.coalesce(
                func.sum(Payment.amount),
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
        )
    )

    total_revenue = float(
        revenue_result.scalar_one()
    )

    appointment_result = await db.execute(
        select(
            func.count(Appointment.id)
        )
        .where(
            Appointment.clinic_id
            == clinic_id,

            Appointment.status
            == AppointmentStatus.COMPLETED,
        )
    )

    completed_appointments = (
        appointment_result.scalar_one()
    )

    if completed_appointments == 0:
        return 0.0

    return round(
        total_revenue
        / completed_appointments,
        2,
    )




async def get_clinic_kpi_dashboard(
    *,
    db: AsyncSession,
    clinic_id : int,
) -> ClinicKPIResponse:

    return ClinicKPIResponse(
        total_revenue=await get_total_revenue(
            db=db,
            clinic_id=clinic_id,
        ),

        total_patients=await get_total_patients(
            db=db,
            clinic_id=clinic_id,
        ),

        total_appointments=await get_total_appointments(
            db=db,
            clinic_id=clinic_id,
        ),

        conversion_rate=await get_conversion_rate(
            db=db,
            clinic_id=clinic_id,
        ),

        completion_rate=await get_completion_rate_total_clinic(
            db=db,
            clinic_id=clinic_id,
        ),

        patients_today=await get_patients_today(
            db=db,
            clinic_id=clinic_id,
        ),

        patients_this_month= await get_patients_this_month(
            db=db,
            clinic_id=clinic_id,
        ),

        appointments_today= await get_appointments_today(
            db=db,
            clinic_id=clinic_id,
        ),
        appointments_this_month=await get_appointments_this_month(
            db=db,
            clinic_id=clinic_id,
        ),
        average_revenue=await get_average_revenue_per_appointment(
            db=db,
            clinic_id=clinic_id,
        )

    )
