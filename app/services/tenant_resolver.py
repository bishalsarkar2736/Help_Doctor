from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.user import User, UserRole
from app.models.doctor import Doctor
from app.try_except.exceptions import ForbiddenError


async def resolve_clinic_id(
    db: AsyncSession,
    user: User,
    clinic_id: int | None = None,
) -> int:

    # -------------------------
    # ADMIN: bound to one clinic
    # -------------------------
    if user.role == UserRole.ADMIN:
        if not user.clinic_id:
            raise ForbiddenError("Admin not assigned to clinic")

        if clinic_id is None:
            raise ForbiddenError("clinic_id required for admin")
        
        if clinic_id is not None and clinic_id != user.clinic_id:
            raise ForbiddenError("Admin not authorized for this clinic")

        return user.clinic_id

    # -------------------------
    # DOCTOR: from doctor profile
    # -------------------------
    if user.role == UserRole.DOCTOR:
        doctor = await db.scalar(
            select(Doctor).where(Doctor.user_id == user.id)
        )
        if not doctor:
            raise ForbiddenError("Doctor profile not found")

        if not doctor.clinic_id:
            raise ForbiddenError("Doctor not assigned to clinic")

        if clinic_id is not None and clinic_id != doctor.clinic_id:
            raise ForbiddenError("Doctor not authorized for this clinic")

        return doctor.clinic_id

    # -------------------------
    # PATIENT / OTHER ROLES: not clinic-scoped
    # -------------------------
    if user.role in {UserRole.PATIENT, UserRole.RECEPTIONIST}:
        return clinic_id

    raise ForbiddenError("Invalid role")