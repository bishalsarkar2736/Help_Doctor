from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.doctor import Doctor
from app.try_except.exceptions import ForbiddenError


async def get_doctor_profile(
    db: AsyncSession,
    user_id: int,
) -> Doctor:

    result = await db.execute(
        select(Doctor).where(
            Doctor.user_id == user_id
        )
    )

    doctor = result.scalar_one_or_none()

    if not doctor:
        raise ForbiddenError(
            "Doctor profile not found"
        )

    return doctor