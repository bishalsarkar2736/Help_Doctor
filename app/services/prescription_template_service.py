from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.prescription_template import (
    PrescriptionTemplate,
    PrescriptionTemplateItem,
)

from app.schemas.prescription_template_schema import (
    PrescriptionTemplateCreate,
)

from app.try_except.exceptions import (
    NotFoundError,
)



async def create_prescription_template(
    *,
    db: AsyncSession,
    doctor_id: int,
    data: PrescriptionTemplateCreate,
    clinic_id : int ,
):
    
   

    template = PrescriptionTemplate(
        doctor_id=doctor_id,
        clinic_id=clinic_id,
        name=data.name,
        notes=data.notes,
    )

    db.add(template)

    await db.flush()

    for item in data.items:

        db.add(
            PrescriptionTemplateItem(
                template_id=template.id,
                medicine_name=item.medicine_name,
                dosage=item.dosage,
                frequency=item.frequency,
                duration_days=item.duration_days,
                instructions=item.instructions,
            )
        )

    await db.flush()
    await db.refresh(template)

    return template


async def list_prescription_templates(
    *,
    db: AsyncSession,
    doctor_id: int,
    clinic_id : int,
):
    

    result = await db.execute(
        select(PrescriptionTemplate)
        .where(
            PrescriptionTemplate.doctor_id== doctor_id,
            PrescriptionTemplate.clinic_id== clinic_id,
        )
        .order_by(
            PrescriptionTemplate.name
        )
    )

    return result.scalars().all()


async def get_prescription_template(
    *,
    db: AsyncSession,
    template_id: int,
    doctor_id: int,
    clinic_id : int,
):
    
    result = await db.execute(
        select(PrescriptionTemplate)
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

    return template