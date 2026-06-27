from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.user import User, UserRole
from app.models.doctor import Doctor
from app.models.patient import Patient
from app.try_except.exceptions import ForbiddenError


async def resolve_clinic_id(
    db: AsyncSession,
    user: User,
    clinic_id: int | None = None,
) -> int:

    # -------------------------
    # ADMIN: clinic must be passed explicitly
    # -------------------------
    if user.role == UserRole.ADMIN:
        if not clinic_id:
            raise ForbiddenError("clinic_id required for admin")
        return clinic_id

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

        return doctor.clinic_id

    # -------------------------
    # PATIENT: from patient profile
    # -------------------------
    if user.role == UserRole.PATIENT:
        patient = await db.scalar(
            select(Patient).where(Patient.user_id == user.id)
        )
        if not patient:
            raise ForbiddenError("Patient profile not found")

        if not patient.clinic_id:
            raise ForbiddenError("Patient not assigned to clinic")

        return patient.clinic_id

    raise ForbiddenError("Invalid role")