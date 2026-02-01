from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.postgres import get_db
from app.security.jwt import get_current_user
from app.models.user import User

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


@router.post("/{doctor_id}/verify")
async def verify(
    doctor_id: int,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_user),
):
    return await verify_doctor(db=db, admin=admin, doctor_id=doctor_id)


@router.post("/{doctor_id}/suspend")
async def suspend(
    doctor_id: int,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_user),
):
    return await suspend_doctor(db=db, admin=admin, doctor_id=doctor_id)


@router.post("/{doctor_id}/unsuspend")
async def unsuspend(
    doctor_id: int,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_user),
):
    return await unsuspend_doctor(db=db, admin=admin, doctor_id=doctor_id)


@router.post("/{doctor_id}/activate")
async def activate(
    doctor_id: int,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_user),
):
    return await activate_doctor(db=db, admin=admin, doctor_id=doctor_id)
