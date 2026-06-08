from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, func
from app.core.time import UTC
from datetime import datetime
from app.db.postgres import get_db
from app.security.rbac import require_roles
from app.models.notification import Notification
from app.models.user import User, UserRole
from app.core.cache import get_cache, set_cache, delete_cache

from app.services.notification_service import (
    sync_notifications,
)

router = APIRouter(
    prefix="/notifications",
    tags=["Notifications"],
)


# 🔹 Get user notifications
@router.get("/")
async def get_notifications(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(
        require_roles(UserRole.ADMIN, UserRole.DOCTOR, UserRole.PATIENT)
    ),
):
    result = await db.execute(
        select(Notification)
        .where(Notification.user_id == current_user.id)
        .order_by(Notification.created_at.desc())
    )

    return result.scalars().all()


# 🔹 Mark single notification as read
@router.patch("/{notification_id}/read")
async def mark_notification_read(
    notification_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(
        require_roles(UserRole.ADMIN, UserRole.DOCTOR, UserRole.PATIENT)
    ),
):
    notification = await db.get(Notification, notification_id)

    if not notification:
        raise HTTPException(status_code=404, detail="Notification not found")

    if notification.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not allowed",
        )

    notification.read_at = datetime.now(UTC)
    await db.commit()

    await delete_cache(f"notification_count:{current_user.id}")

    return {"message": "Notification marked as read"}


# 🔹 Mark all as read
@router.patch("/read-all")
async def mark_all_notifications_read(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(
        require_roles(UserRole.ADMIN, UserRole.DOCTOR, UserRole.PATIENT)
    ),
):
    await db.execute(
        update(Notification)
        .where(
            Notification.user_id == current_user.id,
            Notification.read_at.is_(None)
        )
        .values(
            read_at=datetime.now(UTC)
        )
    )

    await db.commit()

    await delete_cache(f"notification_count:{current_user.id}")

    return {"message": "All notifications marked as read"}


# 🔹 Unread count (with caching)
@router.get("/unread/count")
async def unread_notification_count(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(
        require_roles(UserRole.ADMIN, UserRole.DOCTOR, UserRole.PATIENT)
    ),
):
    cache_key = f"notification_count:{current_user.id}"

    cached = await get_cache(cache_key)
    if cached:
        return cached

    result = await db.execute(
        select(func.count(Notification.id)).where(
            Notification.user_id == current_user.id,
            Notification.read_at.is_(None)
        )
    )

    count = result.scalar()

    data = {"count": count}

    await set_cache(cache_key, data, ttl=15)

    return data


@router.get("/sync")
async def sync_notification_events(
    after_id: int | None = None,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(
        require_roles(
            UserRole.ADMIN,
            UserRole.DOCTOR,
            UserRole.PATIENT,
        )
    ),
):

    notifications = await sync_notifications(
        db=db,
        user_id=current_user.id,
        after_id=after_id,
        limit=min(limit, 100),
    )

    return notifications