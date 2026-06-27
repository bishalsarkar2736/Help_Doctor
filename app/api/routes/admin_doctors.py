from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.postgres import get_db
from app.security.rbac import require_roles
from app.models.user import User, UserRole
from app.models.doctor import Doctor

from app.schemas.admin_doctor import AdminDoctorListItem

from app.services.admin_doctor_service import (
    verify_doctor,
    suspend_doctor,
    unsuspend_doctor,
    activate_doctor,
)

router = APIRouter(
    prefix="/admin/doctors",
    tags=["Admin - Doctors"],
)


# ✅ List all doctors (ADMIN ONLY)
@router.get("", response_model=list[AdminDoctorListItem])
async def admin_list_doctors(
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_roles(UserRole.ADMIN)),
    limit: int = Query(20, le=100),
    offset: int = Query(0),
):
    result = await db.execute(
        select(Doctor, User)
        .join(User, Doctor.user_id == User.id)
        .limit(limit)
        .offset(offset)
    )

    rows = result.all()

    return [
        AdminDoctorListItem(
            id=doctor.id,
            name=user.full_name,
            email=user.email,
            specialization=doctor.specialization,
            experience_years=doctor.experience_years,
            bio=doctor.bio,
            is_verified=doctor.is_verified,
            is_active=user.is_active,
        )
        for doctor, user in rows
    ]


# ✅ Verify doctor
@router.post("/{doctor_id}/verify")
async def verify(
    doctor_id: int,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_roles(UserRole.ADMIN)),
):
    return await verify_doctor(db=db, admin=admin, doctor_id=doctor_id)


# ✅ Suspend doctor
@router.post("/{doctor_id}/suspend")
async def suspend(
    doctor_id: int,
    clinic_id: int,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_roles(UserRole.ADMIN)),
):
    return await suspend_doctor(
        db=db, 
        admin=admin, 
        doctor_id=doctor_id,
        clinic_id=clinic_id,
    )


# ✅ Unsuspend doctor
@router.post("/{doctor_id}/unsuspend")
async def unsuspend(
    doctor_id: int,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_roles(UserRole.ADMIN)),
):
    return await unsuspend_doctor(db=db, admin=admin, doctor_id=doctor_id)


# ✅ Activate doctor
@router.post("/{doctor_id}/activate")
async def activate(
    doctor_id: int,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_roles(UserRole.ADMIN)),
):
    return await activate_doctor(db=db, admin=admin, doctor_id=doctor_id)