from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.models.doctor import Doctor
from app.models.prescription import Prescription

from app.services.prescription_pdf_service import (
    generate_prescription_pdf,
)
from app.services.prescription_email_service import (
    send_prescription_email,
)
from app.services.notification_preference_service import (
    get_or_create_preferences,
)

from app.services.notification_receipt_service import (
    mark_email_delivered,
    mark_delivery_failed,
)


import logging

logger = logging.getLogger(__name__)


async def handle_prescription_issued_email(
    *,
    db,
    validated,
    event_id,
):
    result = await db.execute(
        select(Prescription)
        .options(
            selectinload(
                Prescription.patient
            ),
            selectinload(
                Prescription.doctor
            ).selectinload(
                Doctor.user
            ),
            selectinload(
                Prescription.items
            ),
            selectinload(
                Prescription.appointment
            ),
        )
        .where(
            Prescription.id
            == validated.prescription_id
        )
    )

    prescription = (
        result.scalar_one_or_none()
    )

    if not prescription:
        return

    if not prescription.patient:
        return

    if not prescription.patient.email:
        return
    
    prefs = await get_or_create_preferences(
        db,
        prescription.patient.id,
    )

    if not prefs.email_enabled:
        logger.info(
            "prescription_email_disabled",
            extra={
                "patient_id": prescription.patient.id,
                "prescription_id": prescription.id,
            },
        )
        return
    

    pdf_bytes = generate_prescription_pdf(
        prescription
    )

    try:
        await send_prescription_email(
            email=prescription.patient.email,
            prescription_id=prescription.id,
            pdf_bytes=pdf_bytes,
        )

        await mark_email_delivered(
            event_id=event_id,
        )

    except Exception as exc:

        await mark_delivery_failed(
            event_id=event_id,
            error=str(exc),
        )

        logger.exception(
            "prescription_email_failed",
            extra={
                "prescription_id": prescription.id,
                "event_id": str(event_id),
            },
        )

        raise