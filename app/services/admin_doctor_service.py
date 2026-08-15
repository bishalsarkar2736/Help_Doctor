from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.time import UTC
from app.models.clinic import Clinic
from app.models.doctor import Doctor, DoctorStatus
from app.models.user import User, UserRole
from app.try_except.exceptions import (
    NotFoundError,
    ForbiddenError,
    BadRequestError,
)


async def _admin_only(user: User):
    if user.role != UserRole.ADMIN:
        raise ForbiddenError("Admin access required")


async def _get_doctor(db: AsyncSession, doctor_id: int) -> Doctor:
    doctor = await db.scalar(
        select(Doctor).where(Doctor.id == doctor_id)
    )
    if not doctor:
        raise NotFoundError("Doctor not found")
    return doctor


async def approve_doctor(
    db: AsyncSession,
    admin: User,
    doctor_id: int,
    clinic_id: int,
):
    """Approve a doctor into the admin's clinic (verification)."""
    await _admin_only(admin)

    doctor = await _get_doctor(db, doctor_id)

    # A clinic admin may only approve unassigned applicants or their own
    # doctors — the same rule reject_doctor states, and the same boundary
    # suspend_doctor and reinstate_doctor enforce in their queries.
    #
    # This function is the only writer of Doctor.clinic_id, and it looked its
    # subject up by primary key alone, so a clinic admin could name any
    # doctor_id and pull that doctor INTO their own clinic. resolve_clinic_id
    # pins the TARGET clinic to the caller's, which bounds where the doctor can
    # be moved to but not who may be moved; doctor ids are sequential, so every
    # doctor on the platform was reachable.
    #
    # Doctor.clinic_id is an authorization input rather than a label:
    # may_subscribe gates doctor_queue:{id} on it, GET /appointments/queue
    # authorizes with it, a doctor's PHI scope resolves from it, and new
    # appointments are stamped with it. Capturing the row manufactured all of
    # those at once.
    if doctor.clinic_id is not None and doctor.clinic_id != admin.clinic_id:
        raise ForbiddenError("Cannot approve another clinic's doctor")

    clinic = await db.scalar(
        select(Clinic).where(Clinic.id == clinic_id)
    )
    if not clinic:
        raise NotFoundError("Clinic not found")

    doctor.clinic_id = clinic.id
    doctor.status = DoctorStatus.APPROVED
    doctor.approved_by = admin.id
    doctor.approved_at = datetime.now(UTC)
    # Clear any prior rejection.
    doctor.rejected_by = None
    doctor.rejected_at = None
    doctor.rejection_reason = None

    await db.flush()

    return {"message": "Doctor approved", "status": doctor.status.value}


async def reject_doctor(
    db: AsyncSession,
    admin: User,
    doctor_id: int,
    reason: str | None = None,
):
    await _admin_only(admin)

    doctor = await _get_doctor(db, doctor_id)

    # A clinic admin may only reject unassigned applicants or their own doctors.
    if doctor.clinic_id is not None and doctor.clinic_id != admin.clinic_id:
        raise ForbiddenError("Cannot reject another clinic's doctor")

    doctor.status = DoctorStatus.REJECTED
    doctor.rejected_by = admin.id
    doctor.rejected_at = datetime.now(UTC)
    doctor.rejection_reason = reason

    await db.flush()

    return {"message": "Doctor rejected", "status": doctor.status.value}


async def suspend_doctor(
    db: AsyncSession,
    admin: User,
    doctor_id: int,
):
    await _admin_only(admin)

    doctor = await db.scalar(
        select(Doctor).where(
            Doctor.id == doctor_id,
            Doctor.clinic_id == admin.clinic_id,
        )
    )
    if not doctor:
        raise NotFoundError("Doctor not found")

    if doctor.status != DoctorStatus.APPROVED:
        raise BadRequestError("Only approved doctors can be suspended")

    doctor.status = DoctorStatus.SUSPENDED
    await db.flush()

    return {"message": "Doctor suspended", "status": doctor.status.value}


async def reinstate_doctor(
    db: AsyncSession,
    admin: User,
    doctor_id: int,
):
    """Return a suspended doctor to approved status."""
    await _admin_only(admin)

    doctor = await db.scalar(
        select(Doctor).where(
            Doctor.id == doctor_id,
            Doctor.clinic_id == admin.clinic_id,
        )
    )
    if not doctor:
        raise NotFoundError("Doctor not found")

    if doctor.status != DoctorStatus.SUSPENDED:
        raise BadRequestError("Only suspended doctors can be reinstated")

    doctor.status = DoctorStatus.APPROVED
    doctor.approved_by = admin.id
    doctor.approved_at = datetime.now(UTC)
    await db.flush()

    return {"message": "Doctor reinstated", "status": doctor.status.value}
