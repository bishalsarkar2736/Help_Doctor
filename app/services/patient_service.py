from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.patient import Patient
from app.schemas.patient import PatientCreate, PatientUpdate
from app.try_except.exceptions import BadRequestError, NotFoundError


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


async def get_my_patient(
    db: AsyncSession,
    user_id: int,
) -> Patient:
    result = await db.execute(
        select(Patient).where(Patient.user_id == user_id)
    )
    patient = result.scalar_one_or_none()

    if patient is None:
        raise NotFoundError("Patient profile not found")

    return patient


async def update_my_patient(
    db: AsyncSession,
    user_id: int,
    patient_in: PatientUpdate,
) -> Patient:
    patient = await get_my_patient(db, user_id)

    for field, value in patient_in.model_dump(exclude_unset=True).items():
        setattr(patient, field, value)

    await db.flush()
    await db.refresh(patient)

    return patient