
from sqlalchemy import select

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.appointment import Appointment
from app.models.prescription import Prescription
from app.models.payment import Payment
from app.services.clinic_context_service import (
    get_current_clinic,
)


async def get_patient_history(
    *,
    db: AsyncSession,
    patient_id: int,
):
    
    clinic = await get_current_clinic(db)

    timeline = []

    # appointments

    result = await db.execute(
        select(Appointment)
        .where(
            Appointment.patient_id == patient_id,
            Appointment.clinic_id == clinic.id,
        )
    )

    appointments = result.scalars().all()

    for appointment in appointments:

        timeline.append(
            {
                "type": "appointment",
                "title": "Appointment",
                "reference_id": appointment.id,
                "occurred_at":
                    appointment.created_at,
            }
        )

    # prescriptions

    result = await db.execute(
        select(Prescription)
        .where(
            Prescription.patient_id == patient_id,
            Prescription.clinic_id == clinic.id,
        )
    )

    prescriptions = result.scalars().all()

    for prescription in prescriptions:

        timeline.append(
            {
                "type": "prescription",
                "title":
                    "Prescription Issued",
                "reference_id":
                    prescription.id,
                "occurred_at":
                    prescription.issued_at,
            }
        )

    # payments

    result = await db.execute(
        select(Payment)
        .where(
            Payment.patient_id == patient_id,
            Payment.clinic_id == clinic.id,
        )
    )

    payments = result.scalars().all()

    for payment in payments:

        timeline.append(
            {
                "type": "payment",
                "title":
                    "Payment",
                "reference_id":
                    payment.id,
                "occurred_at":
                    payment.created_at,
            }
        )

    timeline.sort(
        key=lambda x:
        x["occurred_at"],
        reverse=True,
    )

    return {
        "patient_id": patient_id,
        "timeline": timeline,
    }