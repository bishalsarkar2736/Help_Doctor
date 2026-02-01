from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select,update,func
from app.db.postgres import get_db
from app.security.jwt import get_current_user
from app.models.notification import Notification
from app.models.user import User

router = APIRouter(
    prefix="/notifications",
    tags=["Notifications"],
)


@router.get("/")
async def get_notifications(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Notification)
        .where(Notification.user_id == current_user.id)
        .order_by(Notification.created_at.desc())
    )

    return result.scalars().all()



@router.patch("/{notification_id}/read")
async def mark_notification_read(
    notification_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    notification = await db.get(Notification, notification_id)

    if not notification:
        raise HTTPException(404, "Notification not found")

    if notification.user_id != current_user.id:
        raise HTTPException(403, "Not allowed")

    notification.is_read = True
    await db.commit()

    return {"message": "Notification marked as read"}


@router.patch("/read-all")
async def mark_all_notifications_read(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await db.execute(
        update(Notification)
        .where(
            Notification.user_id == current_user.id,
            Notification.is_read == False,
        )
        .values(is_read=True)
    )
    await db.commit()

    return {"message": "All notifications marked as read"}


@router.get("/unread/count")
async def unread_notification_count(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(func.count(Notification.id))
        .where(
            Notification.user_id == current_user.id,
            Notification.is_read == False,
        )
    )
    return {"count": result.scalar()}
