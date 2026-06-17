from fastapi import APIRouter, Depends,Query

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.postgres import get_db

from app.models.user import (
    User,
    UserRole,
)

from app.security.rbac import require_roles

from app.core.cache import (
    get_cache,
    set_cache,
)

from app.services.notification_service import (
    sync_notifications,
)

from app.services.notification_center_service import (
    get_notifications,
    get_unread_notification_count,
    mark_all_notifications_read,
    mark_notification_read,
)

from app.schemas.notification_schema import (
    NotificationResponse,
    NotificationMarkReadResponse,
    NotificationMarkAllReadResponse,
    NotificationUnreadCountResponse,
)

from app.models.notification import (
    NotificationCategory,
)






router = APIRouter(
    prefix="/notifications",
    tags=["Notifications"],
)


# ==========================================
# GET NOTIFICATIONS
# ==========================================

@router.get(
    "/",
    response_model=list[
        NotificationResponse
    ],
)
async def get_user_notifications(
    limit: int = Query(
        default=50,
        ge=1,
        le=100,
    ),
    offset: int = Query(
        default=0,
        ge=0,
    ),
    is_read: bool | None = Query(
        default=None,
    ),

    category: NotificationCategory | None = Query(
        default=None,
    ),

    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(
        require_roles(
            UserRole.ADMIN,
            UserRole.DOCTOR,
            UserRole.PATIENT,
        )
    ),
):
    return await get_notifications(
        db=db,
        user_id=current_user.id,
        limit=limit,
        offset=offset,
        is_read=is_read,
        category=category,
    )


# ==========================================
# MARK SINGLE READ
# ==========================================

@router.patch(
    "/{notification_id}/read",
    response_model=NotificationMarkReadResponse,
)
async def mark_single_notification_read(
    notification_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(
        require_roles(
            UserRole.ADMIN,
            UserRole.DOCTOR,
            UserRole.PATIENT,
        )
    ),
):
    await mark_notification_read(
        db=db,
        user_id=current_user.id,
        notification_id=notification_id,
    )

    await db.commit()

    return {
        "message": "Notification marked as read"
    }


# ==========================================
# MARK ALL READ
# ==========================================

@router.patch(
    "/read-all",
    response_model=NotificationMarkAllReadResponse,
)
async def mark_user_notifications_read(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(
        require_roles(
            UserRole.ADMIN,
            UserRole.DOCTOR,
            UserRole.PATIENT,
        )
    ),
):
    updated = await mark_all_notifications_read(
        db=db,
        user_id=current_user.id,
    )

    await db.commit()

    return {
        "message": "All notifications marked as read",
        "updated": updated,
    }


# ==========================================
# UNREAD COUNT
# ==========================================

@router.get(
    "/unread/count",
    response_model=NotificationUnreadCountResponse,
)
async def unread_notification_count(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(
        require_roles(
            UserRole.ADMIN,
            UserRole.DOCTOR,
            UserRole.PATIENT,
        )
    ),
):
    cache_key = (
        f"notification_count:{current_user.id}"
    )

    cached = await get_cache(cache_key)

    if cached:
        return cached

    count = await get_unread_notification_count(
        db=db,
        user_id=current_user.id,
    )

    data = {
        "count": count,
    }

    await set_cache(
        cache_key,
        data,
        ttl=15,
    )

    return data


# ==========================================
# SYNC EVENTS
# ==========================================

@router.get(
    "/sync",
    response_model=list[
        NotificationResponse
    ],
)
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
    return await sync_notifications(
        db=db,
        user_id=current_user.id,
        after_id=after_id,
        limit=min(limit, 100),
    )