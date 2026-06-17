from fastapi import APIRouter
from fastapi import Depends

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.postgres import get_db

from app.models.user import (
    User,
    UserRole,
)

from app.security.rbac import require_roles

from app.services.notification_preference_service import (
    get_or_create_preferences,
    update_preferences,
)

from app.schemas.notification_preference import (
    NotificationPreferenceResponse,
    NotificationPreferenceUpdate,
)


router = APIRouter(
    prefix="/notification-preferences",
    tags=["Notification Preferences"],
)


@router.get(
    "/",
    response_model=NotificationPreferenceResponse,
)
async def get_preferences(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(
        require_roles(
            UserRole.ADMIN,
            UserRole.DOCTOR,
            UserRole.PATIENT,
        )
    ),
):
    prefs = await get_or_create_preferences(
        db,
        current_user.id,
    )

    return prefs


@router.patch(
    "/",
    response_model=NotificationPreferenceResponse,
)
async def update_preferences(
    payload: NotificationPreferenceUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(
        require_roles(
            UserRole.ADMIN,
            UserRole.DOCTOR,
            UserRole.PATIENT,
        )
    ),
):
    prefs = await update_preferences(
        db=db,
        user_id=current_user.id,
        email_enabled=payload.email_enabled,
        push_enabled=payload.push_enabled,
        realtime_enabled=payload.realtime_enabled,
    )
    
    await db.commit()

    await db.refresh(prefs)

    return prefs