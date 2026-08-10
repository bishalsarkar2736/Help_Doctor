from fastapi import APIRouter, Depends,Query

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.postgres import get_db

from app.models.user import (
    User,
    UserRole,
)

from app.security.rbac import require_roles
from app.try_except.exceptions import ForbiddenError, NotFoundError

from app.core.cache import (
    get_cache,
    set_cache,
)

from app.services.notification_service import (
    sync_notifications,
)

from app.services.notification_receipt_service import (
    mark_notifications_seen,
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
    Notification,
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
# MARK SEEN
# ==========================================

@router.patch(
    "/{notification_id}/seen",
    response_model=NotificationMarkReadResponse,
)
async def mark_single_notification_seen(
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
    """Mark one notification as seen.

    seen_at could previously only be written through the WebSocket
    `notification_seen` message, so any client without a live socket — a mobile
    app, a polling client, a browser whose connection dropped — could mark a
    notification READ but never SEEN. The two dimensions had entirely different
    reachability for no reason anybody chose.

    Ownership is resolved the same way as /read: 404 when it does not exist, 403
    when it is not yours. Deliberately identical, so the two endpoints cannot
    drift apart — including in what they reveal, which is a pre-existing
    property of /read and not something this endpoint should decide alone.

    Bulk marking already exists over the WebSocket and is not duplicated here;
    this is the smallest addition that closes the gap.
    """
    notification = await db.get(Notification, notification_id)

    if notification is None:
        raise NotFoundError("Notification not found")

    if notification.user_id != current_user.id:
        raise ForbiddenError("Not allowed")

    # Reuses the existing writer, which is already user-scoped, write-once and
    # bulk-capable. Passing a single id keeps one implementation of what "seen"
    # means rather than adding a second.
    await mark_notifications_seen(
        db=db,
        notification_ids=[notification_id],
        user_id=current_user.id,
    )

    return {
        "message": "Notification marked as seen"
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