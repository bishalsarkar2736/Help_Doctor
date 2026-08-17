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

from app.services.tenant_resolver import resolve_clinic_id



router = APIRouter(prefix="/admin/analytics", tags=["Admin Analytics"])


@router.get("/overview")
async def dashboard_overview(
    clinic_id : int,
    db: AsyncSession = Depends(get_db),
    admin : User =Depends(
        require_roles(UserRole.ADMIN)
    ),
):
    
    resolved_clinic_id = await resolve_clinic_id(
        db=db,
        user=admin,
        clinic_id=clinic_id,
    )

    return await get_dashboard_overview(
        db=db,
        clinic_id=resolved_clinic_id,
    )


@router.get("/daily")
async def daily_appointments(
    clinic_id : int,
    days: int = 7,
    db: AsyncSession = Depends(get_db),
    admin=Depends(
        require_roles(UserRole.ADMIN)
    ),
):
    
    resolved_clinic_id = await resolve_clinic_id(
        db=db,
        user=admin,
        clinic_id=clinic_id,
    )

    return await get_daily_appointments(
        db=db,
        clinic_id=resolved_clinic_id,
        days=days,
    )


@router.get("/top-doctors")
async def top_doctors(
    clinic_id : int,
    limit: int = 5,
    db: AsyncSession = Depends(get_db),
    admin : User =Depends(
        require_roles(UserRole.ADMIN)
    ),
):
    
    resolved_clinic_id = await resolve_clinic_id(
        db=db,
        user=admin,
        clinic_id=clinic_id,
    )

    return await get_top_doctors_by_appointments(
        db=db,
        clinic_id=resolved_clinic_id,
        limit=limit,
    )


@router.get("/no-show-analytics")
async def no_show_analytics(
    clinic_id :int,
    db: AsyncSession = Depends(get_db),
    admin : User =Depends(
        require_roles(UserRole.ADMIN)
    ),
):
    
    resolved_clinic_id = await resolve_clinic_id(
        db=db,
        user=admin,
        clinic_id=clinic_id,
    )

    return await get_no_show_analytics(
        db=db,
        clinic_id=resolved_clinic_id,
    )

@router.get("/cancellation-analytics")
async def cancellation_analytics(
    clinic_id : int,
    db: AsyncSession = Depends(get_db),
    admin : User =Depends(
        require_roles(UserRole.ADMIN)
    ),
):
    
    resolved_clinic_id = await resolve_clinic_id(
        db=db,
        user=admin,
        clinic_id=clinic_id,
    )

    return await get_cancellation_analytics(
        db=db,
        clinic_id=resolved_clinic_id,
    )


@router.get("/doctor-utilization/{doctor_id}")
async def doctor_utilization(
    clinic_id : int,
    doctor_id: int,
    db: AsyncSession = Depends(get_db),
    admin : User =Depends(
        require_roles(UserRole.ADMIN)
    ),
):
    
    resolved_clinic_id = await resolve_clinic_id(
        db=db,
        user=admin,
        clinic_id=clinic_id,
    )

    return await get_doctor_utilization(
        db=db,
        clinic_id=resolved_clinic_id,
        doctor_id=doctor_id,
    )


@router.get("/system-utilization")
async def system_utilization(
    clinic_id : int,
    db: AsyncSession = Depends(get_db),
    admin : User =Depends(
        require_roles(UserRole.ADMIN)
    ),
):
    
    resolved_clinic_id = await resolve_clinic_id(
        db=db,
        user=admin,
        clinic_id=clinic_id,
    )

    return await get_system_utilization(
        db=db,
        clinic_id=resolved_clinic_id,
    )



# PLATFORM TELEMETRY, NOT CLINIC ANALYTICS.
#
# Unlike every other route in this module, these two aggregate Notification
# rows with no tenant predicate, so a clinic admin was reading totals and
# delivery rates that span every tenant on the platform.
#
# They are not scoped to a clinic because they cannot honestly be: notifications
# carry no clinic_id, and their recipients include patients, who are global
# identities with clinic_id NULL. Joining through users would silently drop
# every patient notification from the totals — inventing a number rather than
# scoping one. So the numbers stay platform-wide and move to the platform role.
@router.get("/notifications")
async def notification_analytics(
    db: AsyncSession = Depends(get_db),
    admin : User =Depends(
        require_roles(UserRole.SUPER_ADMIN)
    ),
):
    return await get_notification_analytics(
        db=db,
    )


@router.get("/notifications/daily")
async def daily_notification_volume(
    db: AsyncSession = Depends(get_db),
    admin : User =Depends(
        require_roles(UserRole.SUPER_ADMIN)
    ),
):
    return await get_daily_notification_volume(
        db=db,
    )