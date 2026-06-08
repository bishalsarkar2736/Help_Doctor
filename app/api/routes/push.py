from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from app.db.postgres import get_db
from app.security.rbac import require_roles
from app.models.user import User, UserRole
from app.models.push_subscription import PushSubscription

router = APIRouter(prefix="/push", tags=["Push Notifications"])


@router.post("/subscribe")
async def subscribe_push(
    data: dict,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_roles(UserRole.ADMIN, UserRole.DOCTOR, UserRole.PATIENT)),
):
    sub = PushSubscription(
        user_id=user.id,
        endpoint=data["endpoint"],
        keys=data["keys"],
    )

    try:
        db.add(sub)
        await db.commit()
    except IntegrityError:
        await db.rollback()  # already exists → ignore safely

    return {"message": "Subscribed"}