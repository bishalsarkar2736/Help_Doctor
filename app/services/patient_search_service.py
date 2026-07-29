from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.patient import Patient
from app.models.user import User
from app.schemas.patient_search import PatientSearchOut


async def search_patients(
    *,
    db: AsyncSession,
    q: str,
    limit: int = 20,
    offset: int = 0,
) -> list[PatientSearchOut]:
    """
    Search patients by:

    - Full name
    - Email
    - Phone number

    Results are paginated.
    """

    query = (
        select(Patient)
        .options(
            selectinload(Patient.user),
        )
        .join(
            User,
            Patient.user_id == User.id,
        )
    )

    q = q.strip()

    if q:
        pattern = f"%{q}%"

        query = query.where(
            or_(
                User.full_name.ilike(pattern),
                User.email.ilike(pattern),
                Patient.phone.ilike(pattern),
            )
        )

    query = (
        query.order_by(User.full_name.asc())
        .offset(offset)
        .limit(limit)
    )

    result = await db.execute(query)

    patients = result.scalars().all()

    return [
        PatientSearchOut(
            id=patient.id,
            user_id=patient.user_id,
            full_name=patient.user.full_name or "",
            email=patient.user.email,
            phone=patient.phone,
        )
        for patient in patients
    ]