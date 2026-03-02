from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.patient import Patient
from app.schemas.patient import PatientCreate
from app.try_except.exceptions import BadRequestError


async def create_patient(
        db:AsyncSession,
        user_id: int,
        patient_in:PatientCreate,
) -> Patient:
    
    result = await db.execute(
        select(Patient).where(Patient.user_id == user_id)
    )

    if result.scalar_one_or_none():
        raise BadRequestError("Patient profile already exists")
    
    patient = Patient(
        user_id = user_id,
        **patient_in.model_dump()
    )

    db.add(patient)
    await db.flush()
    await db.refresh(patient)

    return patient