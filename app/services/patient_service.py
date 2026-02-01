from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from fastapi import HTTPException,status

from app.models.patient import Patient
from app.schemas.patient import PatientCreate

async def create_patient(
        db:AsyncSession,
        user_id: int,
        patient_in:PatientCreate,
) -> Patient:
    
    result = await db.execute(
        select(Patient).where(Patient.user_id == user_id)
    )

    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Patient profile already exists",
        )
    
    patient = Patient(
        user_id = user_id,
        **patient_in.model_dump()
    )

    db.add(patient)
    await db.commit()
    await db.refresh(patient)

    return patient