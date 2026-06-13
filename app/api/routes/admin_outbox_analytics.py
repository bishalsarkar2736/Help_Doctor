from fastapi import APIRouter, Depends
from app.security.rbac import require_roles
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.user import UserRole,User
from app.db.postgres import get_db

from app.services.outbox_analytics_service import (
    get_outbox_overview,
    get_outbox_success_rate,
    get_outbox_queue_depth,
    get_outbox_processing_latency,
    get_outbox_failures_by_day,

)

router = APIRouter(prefix="/admin/outbox/analytics", tags=["Admin Outbox Analytics"])

@router.get("/overview")
async def outbox_overview(
    db: AsyncSession = Depends(get_db),
    admin : User =Depends(
        require_roles(UserRole.ADMIN)
    ),
):
    return await get_outbox_overview(db)



@router.get("/success-rate")
async def outbox_success_rate(
    db: AsyncSession = Depends(get_db),
    admin : User =Depends(
        require_roles(UserRole.ADMIN)
    ),
):
    return await get_outbox_success_rate(db)


@router.get("/queue-depth")
async def outbox_queue_depth(
    db: AsyncSession = Depends(get_db),
    admin : User =Depends(
        require_roles(UserRole.ADMIN)
    ),
):
    return await get_outbox_queue_depth(db)


@router.get("/latency")
async def outbox_latency(
    db: AsyncSession = Depends(get_db),
    admin : User =Depends(
        require_roles(UserRole.ADMIN)
    ),
):
    return await get_outbox_processing_latency(db)


@router.get("/failures")
async def outbox_failures(
    days: int = 30,
    db: AsyncSession = Depends(get_db),
    admin : User =Depends(
        require_roles(UserRole.ADMIN)
    ),
):
    return await get_outbox_failures_by_day(
        db,
        days,
    )