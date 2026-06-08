from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select,or_

from app.db.postgres import get_db
from app.models.user import User, UserRole
from app.models.appointment import Appointment

from app.services.appointment_service import admin_force_cancel_appointment
from app.services.notification_service import notify_user

from app.security.rbac import require_roles
from app.schemas.admin_user import AdminUserItem
from app.websocket.manager import manager
from app.services.realtime_service import notify_admins


router = APIRouter(prefix="/admin", tags=["Admin"])


# 🔹 Audit logs (admin only)
@router.get("/audit")
async def appointment_audit(
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_roles(UserRole.ADMIN)),  # ✅ FIXED
):
    result = await db.execute(
        select(Appointment)
        .where(Appointment.cancelled_by.isnot(None))
        .order_by(Appointment.cancelled_at.desc())
    )

    return result.scalars().all()


# 🔹 List users
# @router.get("/users", response_model=list[AdminUserItem])
# async def list_users(
#     db: AsyncSession = Depends(get_db),
#     admin: User = Depends(require_roles(UserRole.ADMIN)),
#     limit: int = Query(20, le=100),
#     offset: int = Query(0),
# ):
#     result = await db.execute(
#         select(User)
#         .limit(limit)
#         .offset(offset)
#     )

#     return result.scalars().all()


@router.get("/users", response_model=list[AdminUserItem])
async def list_users(
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_roles(UserRole.ADMIN)),

    # ✅ pagination
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0),

    # ✅ filters
    search: str | None = Query(None),
    role: UserRole | None = Query(None),
    is_active: bool | None = Query(None),
):
    query = select(User).order_by(User.id.desc())

    # 🔍 SEARCH
    if search:
        search = search.strip()

        if search:
            pattern = f"%{search}%"

            query = query.where(
                User.full_name.ilike(pattern) |
                User.email.ilike(pattern)
            )

    # 🎯 ROLE FILTER
    if role:
        query = query.where(User.role == role)

    # ⚡ ACTIVE FILTER
    if is_active is not None:
        query = query.where(User.is_active == is_active)

    # 📄 PAGINATION
    query = query.limit(limit).offset(offset)

    result = await db.execute(query)
    users = result.scalars().all()

    return users


# 🔹 Change role
@router.post("/users/{user_id}/role")
async def change_user_role(
    user_id: int,
    role: UserRole,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_roles(UserRole.ADMIN)),
):
    user = await db.get(User, user_id)

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.role = role
    await db.commit()

    return {"message": "Role updated"}


# 🔹 Activate / Deactivate
@router.post("/users/{user_id}/toggle-active")
async def toggle_user_active(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_roles(UserRole.ADMIN)),
):
    user = await db.get(User, user_id)

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # toggle
    user.is_active = not user.is_active
    #await db.commit()

    # ✅ CREATE EVENT
    event = {
        "event": "user.updated",
        "data": {
            "user_id": user.id,
            "is_active": user.is_active,
        }
    }

    # ✅ 1. notify affected user
    await manager.notify_user(user.id, event)

    # ✅ 2. notify all admins (REAL-TIME ADMIN PANEL)
    await notify_admins(db, event)

    return {
        "message": "User status updated",
        "is_active": user.is_active
    }


# 🔹 Force cancel appointment
@router.post("/appointments/{appointment_id}/force-cancel")
async def force_cancel(
    appointment_id: int,
    reason: str,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_roles(UserRole.ADMIN)),  # ✅ FIXED
):
    appointment = await admin_force_cancel_appointment(
        db=db,
        admin=admin,
        appointment_id=appointment_id,
        reason=reason,
    )

    await notify_user(
        db=db,
        user_id=appointment.patient_id,
        title="Appointment Cancelled",
        message="Your appointment was cancelled by admin",
        appointment_id=appointment.id,
    )

    await notify_user(
        db=db,
        user_id=appointment.doctor_id,
        title="Appointment Cancelled",
        message="Appointment was cancelled by admin",
        appointment_id=appointment.id,
    )

    return {"message": "Appointment cancelled"}