from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.prescription_template import (
    PrescriptionTemplate,
)

from app.try_except.exceptions import (
    NotFoundError,
)

from app.services.clinic_context_service import (
    get_current_clinic,
)



async def apply_prescription_template(
    *,
    db: AsyncSession,
    template_id: int,
    doctor_id: int,
):

    clinic = await get_current_clinic(db)

    result = await db.execute(
        select(PrescriptionTemplate)
        .where(
            PrescriptionTemplate.id== template_id,
            PrescriptionTemplate.doctor_id == doctor_id,
            PrescriptionTemplate.clinic_id== clinic.id,
        )
    )

    template = result.scalar_one_or_none()

    if not template:
        raise NotFoundError(
            "Template not found"
        )

    return {
        "template_id": template.id,
        "template_name": template.name,
        "notes": template.notes,
        "items": [
            {
                "medicine_name": item.medicine_name,
                "dosage": item.dosage,
                "frequency": item.frequency,
                "duration_days": item.duration_days,
                "instructions": item.instructions,
            }
            for item in template.items
        ],
    }


async def get_template_items(
    *,
    db: AsyncSession,
    template_id: int,
    doctor_id: int,
):
    
    clinic = await get_current_clinic(db)

    result = await db.execute(
        select(PrescriptionTemplate)
        .where(
            PrescriptionTemplate.id == template_id,
            PrescriptionTemplate.doctor_id == doctor_id,
            PrescriptionTemplate.clinic_id== clinic.id,
        )
    )

    template = result.scalar_one_or_none()

    if not template:
        raise NotFoundError(
            "Template not found"
        )

    return template