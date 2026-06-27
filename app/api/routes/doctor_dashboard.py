from fastapi import APIRouter, Depends, HTTPException,status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.postgres import get_db
from app.models.user import UserRole, User
from app.security.rbac import require_roles
from app.models.doctor import Doctor
from app.services.doctor_dashboard_service import (
    get_doctor_dashboard,
)
from app.services.doctor_revenue_trend_service import get_doctor_monthly_revenue



router = APIRouter(
    prefix="/doctor",
    tags=["Doctor Dashboard"],
)


@router.get("/dashboard")
async def doctor_dashboard(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(
        require_roles(UserRole.DOCTOR)
    ),
):
    result = await db.execute(
        select(Doctor).where(
            Doctor.user_id == current_user.id
        )
    )

    doctor = result.scalar_one_or_none()

    if not doctor:
        raise HTTPException(
            status_code=404,
            detail="Doctor profile not found",
        )

    return await get_doctor_dashboard(
        db=db,
        doctor_id=doctor.id,
        clinic_id=doctor.clinic_id,
    )


@router.get(
    "/revenue-trend"
)
async def doctor_revenue_trend(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(
        require_roles(
            UserRole.DOCTOR
        )
    ),
):
    
    result = await db.execute(
        select(Doctor)
        .where(
            Doctor.user_id
            == current_user.id
        )
    )

    doctor = result.scalar_one_or_none()

    if not doctor:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Doctor profile not found for this user."
        )

    return await get_doctor_monthly_revenue(
    db=db,
    doctor_id=doctor.id,
    clinic_id=doctor.clinic_id,
)