from sqlalchemy import func
from sqlalchemy import select

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.appointment import Appointment

from app.services.clinic_context_service import (
    get_current_clinic,
)


async def get_followup_analytics(
    *,
    db: AsyncSession,
):
    clinic = await get_current_clinic(db)

    # -------------------------
    # total unique patients
    # -------------------------

    total_patients_result = await db.execute(
        select(
            func.count(
                func.distinct(
                    Appointment.patient_id
                )
            )
        )
        .where(
            Appointment.clinic_id
            == clinic.id
        )
    )

    total_patients = (
        total_patients_result.scalar_one()
    )

    # -------------------------
    # patients with >= 2 visits
    # -------------------------

    followup_result = await db.execute(
        select(
            Appointment.patient_id
        )
        .where(
            Appointment.clinic_id
            == clinic.id
        )
        .group_by(
            Appointment.patient_id
        )
        .having(
            func.count(
                Appointment.id
            ) >= 2
        )
    )

    followup_patients = len(
        followup_result.all()
    )

    if total_patients == 0:
        followup_rate = 0.0
    else:
        followup_rate = round(
            (
                followup_patients
                / total_patients
            ) * 100,
            2,
        )

    return {
        "total_patients":
            total_patients,

        "patients_with_followups":
            followup_patients,

        "followup_rate":
            followup_rate,
    }