from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.doctor import Doctor
from app.models.user import User
from app.schemas.doctor_search import DoctorSearchOut


async def search_doctors(
    *,
    db: AsyncSession,
    q: str,
    limit: int = 20,
    offset: int = 0,
) -> list[DoctorSearchOut]:
    """
    Search doctors by:

    - Full name
    - Email
    - Specialization

    Results are paginated.
    """

    query = (
        select(Doctor)
        .options(
            selectinload(Doctor.user),
        )
        .join(
            User,
            Doctor.user_id == User.id,
        )
    )

    q = q.strip()

    if q:
        pattern = f"%{q}%"

        query = query.where(
            or_(
                User.full_name.ilike(pattern),
                User.email.ilike(pattern),
                Doctor.specialization.ilike(pattern),
            )
        )

    query = (
        query.order_by(User.full_name.asc())
        .offset(offset)
        .limit(limit)
    )

    result = await db.execute(query)

    doctors = result.scalars().all()

    return [
        DoctorSearchOut(
            id=doctor.id,
            full_name=doctor.user.full_name or "",
            email=doctor.user.email,
            specialization=doctor.specialization,
        )
        for doctor in doctors
    ]