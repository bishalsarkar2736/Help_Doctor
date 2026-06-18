from fastapi import APIRouter, Depends
from app.security.rbac import require_roles
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.user import UserRole,User
from app.db.postgres import get_db
from app.services.admin_analytics_service import (
    get_dashboard_overview,
    get_daily_appointments,
    get_top_doctors_by_appointments,
    get_no_show_analytics,
    get_cancellation_analytics,
    get_doctor_utilization,
    get_system_utilization,
    get_daily_notification_volume,
    get_notification_analytics,
)

router = APIRouter(prefix="/admin/analytics", tags=["Admin Analytics"])


@router.get("/overview")
async def dashboard_overview(
    db: AsyncSession = Depends(get_db),
    admin : User =Depends(
        require_roles(UserRole.ADMIN)
    ),
):
    return await get_dashboard_overview(db)


@router.get("/daily")
async def daily_appointments(
    days: int = 7,
    db: AsyncSession = Depends(get_db),
    admin=Depends(
        require_roles(UserRole.ADMIN)
    ),
):
    return await get_daily_appointments(db, days)


@router.get("/top-doctors")
async def top_doctors(
    limit: int = 5,
    db: AsyncSession = Depends(get_db),
    admin : User =Depends(
        require_roles(UserRole.ADMIN)
    ),
):
    return await get_top_doctors_by_appointments(db, limit)


@router.get("/no-show-analytics")
async def no_show_analytics(
    db: AsyncSession = Depends(get_db),
    admin : User =Depends(
        require_roles(UserRole.ADMIN)
    ),
):
    return await get_no_show_analytics(
        db=db,
    )

@router.get("/cancellation-analytics")
async def cancellation_analytics(
    db: AsyncSession = Depends(get_db),
    admin : User =Depends(
        require_roles(UserRole.ADMIN)
    ),
):
    return await get_cancellation_analytics(
        db=db,
    )


@router.get("/doctor-utilization/{doctor_id}")
async def doctor_utilization(
    doctor_id: int,
    db: AsyncSession = Depends(get_db),
    admin : User =Depends(
        require_roles(UserRole.ADMIN)
    ),
):
    return await get_doctor_utilization(db, doctor_id)


@router.get("/system-utilization")
async def system_utilization(
    db: AsyncSession = Depends(get_db),
    admin : User =Depends(
        require_roles(UserRole.ADMIN)
    ),
):
    return await get_system_utilization(db)



@router.get("/notifications")
async def notification_analytics(
    db: AsyncSession = Depends(get_db),
    admin : User =Depends(
        require_roles(UserRole.ADMIN)
    ),
):
    return await get_notification_analytics(db)


@router.get("/notifications/daily")
async def daily_notification_volume(
    db: AsyncSession = Depends(get_db),
    admin : User =Depends(
        require_roles(UserRole.ADMIN)
    ),
):
    return await get_daily_notification_volume(db)