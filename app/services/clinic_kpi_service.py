from sqlalchemy import func
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.appointment import Appointment,AppointmentStatus
from app.models.patient import Patient
from app.models.payment import Payment
from datetime import date
from app.services.clinic_context_service import (
    get_current_clinic,
)
from app.schemas.clinic_kpi_schema import (
    ClinicKPIResponse,
)



async def get_total_patients(
    *,
    db: AsyncSession,
) -> int:

    clinic = await get_current_clinic(db)

    result = await db.execute(
        select(
            func.count(
                Patient.id
            )
        )
        .where(
            Patient.clinic_id
            == clinic.id
        )
    )

    return result.scalar_one()


async def get_total_appointments(
    *,
    db: AsyncSession,
) -> int:

    clinic = await get_current_clinic(db)

    result = await db.execute(
        select(
            func.count(
                Appointment.id
            )
        )
        .where(
            Appointment.clinic_id
            == clinic.id
        )
    )

    return result.scalar_one()


async def get_total_revenue(
    db: AsyncSession,
) -> float:
    
    clinic = await get_current_clinic(db)

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
            Payment.status
            == "SUCCESS",

            Appointment.clinic_id
            == clinic.id,

            Payment.clinic_id
            == clinic.id,
        )

    )

    return float(
        result.scalar_one()
    )


async def get_conversion_rate(
    *,
    db: AsyncSession,
) -> float:

    clinic = await get_current_clinic(db)

    total_result = await db.execute(
        select(
            func.count(
                Appointment.id
            )
        )
        .where(
            Appointment.clinic_id
            == clinic.id
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
            == clinic.id,
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


async def get_completion_rate(
    *,
    db: AsyncSession,
) -> float:

    clinic = await get_current_clinic(db)

    completed_result = await db.execute(
        select(
            func.count(
                Appointment.id
            )
        )
        .where(
            Appointment.clinic_id
            == clinic.id,

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
            == clinic.id,

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
) -> int:

    clinic = await get_current_clinic(db)

    today = date.today()

    result = await db.execute(
        select(
            func.count(Patient.id)
        )
        .where(
            Patient.clinic_id == clinic.id,
            func.date(
                Patient.created_at
            ) == today,
        )
    )

    return result.scalar_one()



async def get_patients_this_month(
    *,
    db: AsyncSession,
) -> int:

    clinic = await get_current_clinic(db)

    today = date.today()

    result = await db.execute(
        select(
            func.count(Patient.id)
        )
        .where(
            Patient.clinic_id == clinic.id,

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



async def get_clinic_kpi_dashboard(
    *,
    db: AsyncSession,
) -> ClinicKPIResponse:

    return ClinicKPIResponse(
        total_revenue=await get_total_revenue(
            db=db,
        ),

        total_patients=await get_total_patients(
            db=db,
        ),

        total_appointments=await get_total_appointments(
            db=db,
        ),

        conversion_rate=await get_conversion_rate(
            db=db,
        ),

        completion_rate=await get_completion_rate(
            db=db,
        ),
    )