from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.prescription_template import (
    PrescriptionTemplate,
)

from app.try_except.exceptions import (
    NotFoundError,
)





async def apply_prescription_template(
    *,
    db: AsyncSession,
    template_id: int,
    doctor_id: int,
    clinic_id : int,
):


    result = await db.execute(
        select(PrescriptionTemplate)
        # selectinload, not lazy: `.items` is a relationship, and touching it
        # outside a greenlet raises MissingGreenlet under async SQLAlchemy — a
        # 500 on every request that applies a template.
        .options(selectinload(PrescriptionTemplate.items))
        .where(
            PrescriptionTemplate.id== template_id,
            PrescriptionTemplate.doctor_id == doctor_id,
            PrescriptionTemplate.clinic_id== clinic_id,
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
    clinic_id : int,
):
    
   

    result = await db.execute(
        select(PrescriptionTemplate)
        # selectinload, not lazy: `.items` is a relationship, and touching it
        # outside a greenlet raises MissingGreenlet under async SQLAlchemy — a
        # 500 on every prescription that applies a template.
        .options(selectinload(PrescriptionTemplate.items))
        .where(
            PrescriptionTemplate.id == template_id,
            PrescriptionTemplate.doctor_id == doctor_id,
            PrescriptionTemplate.clinic_id== clinic_id,
        )
    )

    template = result.scalar_one_or_none()

    if not template:
        raise NotFoundError(
            "Template not found"
        )

    return template