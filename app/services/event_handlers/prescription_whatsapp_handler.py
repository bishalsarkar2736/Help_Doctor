from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID
from app.models.doctor import Doctor
from app.models.prescription import Prescription
from app.models.user import User
from app.services.notification_preference_service import (
    get_or_create_preferences,
)
from app.schemas.event import PrescriptionIssuedEvent
from app.services.notification_receipt_service import (
    mark_whatsapp_delivered,
    mark_whatsapp_failed,
)

from app.services.prescription_pdf_service import (
    generate_prescription_pdf,
)

from app.services.prescription_whatsapp_service import (
    send_prescription_whatsapp,
)

import logging

logger = logging.getLogger(__name__)


async def handle_prescription_issued_whatsapp(
    *,
    db: AsyncSession,
    validated:PrescriptionIssuedEvent,
    event_id: UUID,
):
    
    result = await db.execute(
        select(Prescription)
        .options(
            selectinload(Prescription.patient).selectinload(
                User.patient,
            ),
            selectinload(Prescription.doctor).selectinload(
                Doctor.user,
            ),
            selectinload(Prescription.items),
            selectinload(Prescription.appointment),
        )
        .where(
            Prescription.id == validated.prescription_id
        )
    )

    prescription = result.scalar_one_or_none()


    if not prescription:
        return


    patient_profile = prescription.patient.patient

    patient_profile = getattr(prescription.patient, "patient", None)

    if not patient_profile:
        logger.warning(
            "patient_profile_missing",
            extra={
                "patient_id": prescription.patient.id,
                "prescription_id": prescription.id,
            },
        )
        return
    

    if not patient_profile.phone:
   
        logger.warning(
            "patient_has_no_phone",
            extra={
                "patient_id": prescription.patient.id,
                "prescription_id": prescription.id,
            },
        )
        return

    prefs = await get_or_create_preferences(
        db,
        prescription.patient.id,
    )


    if not prefs.whatsapp_enabled:
       
        logger.info(
            "prescription_whatsapp_disabled",
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

        await send_prescription_whatsapp(
            phone=patient_profile.phone,
            prescription_id=prescription.id,
            pdf_bytes=pdf_bytes,
        )

        await mark_whatsapp_delivered(
            db=db,
            event_id=event_id,
        )

        logger.info(
        "prescription_whatsapp_sent",
        extra={
            "prescription_id": prescription.id,
            "patient_id": prescription.patient.id,
            "event_id": str(event_id),
        },
    )

    except Exception as exc:

        await mark_whatsapp_failed(
            db=db,
            event_id=event_id,
            error=str(exc),
        )

        logger.exception(
            "prescription_whatsapp_failed",
            extra={
                "prescription_id": prescription.id,
                "event_id": str(event_id),
            },
        )

        raise