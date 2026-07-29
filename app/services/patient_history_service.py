
from sqlalchemy import select,exists

from sqlalchemy.ext.asyncio import AsyncSession
from app.models.patient import Patient
from app.models.appointment import Appointment
from app.models.prescription import Prescription
from app.models.payment import Payment
from app.try_except.exceptions import (
    NotFoundError,
)



async def get_patient_history(
    *,
    db: AsyncSession,
    clinic_id : int,
    patient_id: int,
    limit: int = 50,
    offset: int = 0,
):
    
    patient = await db.scalar(
        select(Patient)
        .where(
            Patient.user_id == patient_id,
            exists().where(
                Appointment.patient_id == Patient.user_id,
                Appointment.clinic_id == clinic_id,
            ),
        )
    )

    if not patient:
        raise NotFoundError("Patient not found")


    timeline = []

    # appointments

    result = await db.execute(
        select(Appointment)
        .where(
            Appointment.patient_id == patient_id,
            Appointment.clinic_id == clinic_id,
        )
    )

    appointments = result.scalars().all()

    for appointment in appointments:

        timeline.append(
            {
                "type": "APPOINTMENT_BOOKED",
                "title": "Appointment Booked",
                "reference_id": appointment.id,
                "occurred_at": appointment.created_at,
            }
        )

        if appointment.confirmed_at:
            timeline.append(
                {
                    "type": "APPOINTMENT_CONFIRMED",
                    "title": "Appointment Confirmed",
                    "reference_id": appointment.id,
                    "occurred_at": appointment.confirmed_at,
                }
            )

        if appointment.completed_at:
            timeline.append(
                {
                    "type": "APPOINTMENT_COMPLETED",
                    "title": "Appointment Completed",
                    "reference_id": appointment.id,
                    "occurred_at": appointment.completed_at,
                }
            )

        if appointment.cancelled_at:
            timeline.append(
                {
                    "type": "APPOINTMENT_CANCELLED",
                    "title": "Appointment Cancelled",
                    "reference_id": appointment.id,
                    "occurred_at": appointment.cancelled_at,
                }
            )


    # prescriptions

    result = await db.execute(
        select(Prescription)
        .where(
            Prescription.patient_id == patient_id,
            Prescription.clinic_id == clinic_id,
        )
    )

    prescriptions = result.scalars().all()


    for prescription in prescriptions:

        timeline.append(
            {
                "type": "PRESCRIPTION_CREATED",
                "title": "Prescription Created",
                "reference_id": prescription.id,
                "occurred_at": prescription.created_at,
            }
        )

        if prescription.issued_at:
            timeline.append(
                {
                    "type": "PRESCRIPTION_ISSUED",
                    "title": "Prescription Issued",
                    "reference_id": prescription.id,
                    "occurred_at": prescription.issued_at,
                }
            )

        if prescription.revision_number > 1:
            timeline.append(
                {
                    "type": "PRESCRIPTION_REVISED",
                    "title": (
                        f"Prescription Revision "
                        f"#{prescription.revision_number}"
                    ),
                    "reference_id": prescription.id,
                    "occurred_at": prescription.created_at,
                }
            )

    # payments

    result = await db.execute(
        select(Payment)
        .where(
            Payment.patient_id == patient_id,
            Payment.clinic_id == clinic_id,
        )
    )

    payments = result.scalars().all()

    for payment in payments:

        if payment.status == "SUCCESS":

            timeline.append(
                {
                    "type": "PAYMENT_SUCCESS",
                    "title": "Payment Successful",
                    "reference_id": payment.id,
                    "occurred_at": payment.created_at,
                }
            )

        # elif payment.status == "REFUNDED":

        #     timeline.append(
        #         {
        #             "type": "PAYMENT_REFUNDED",
        #             "title": "Payment Refunded",
        #             "reference_id": payment.id,
        #             "occurred_at": payment.updated_at
        #             or payment.created_at,
        #         }
        #     )


    timeline = [
        item
        for item in timeline
        if item["occurred_at"] is not None
    ]

    timeline.sort(
        key=lambda x:
        x["occurred_at"],
        reverse=True,
    )

    total_count = len(timeline)

    paginated_timeline = timeline[
        offset : offset + limit
    ]

    return {
        "patient_id": patient_id,
        "total_count": total_count,
        "limit": limit,
        "offset": offset,
        "has_next": (
            offset + limit
        ) < total_count,
        "timeline": paginated_timeline,
    }