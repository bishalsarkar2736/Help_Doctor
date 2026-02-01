from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.postgres import get_db
from app.security.jwt import get_current_user
from app.models.user import User, UserRole
from app.models.appointment import Appointment

from app.services.appointment_service import admin_force_cancel_appointment
from app.services.notification_service import notify_user


router = APIRouter(prefix="/admin", tags=["Admin"])


@router.get("/audit")
async def appointment_audit(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Admin only")

    result = await db.execute(
        select(Appointment)
        .where(Appointment.cancelled_by.isnot(None))
        .order_by(Appointment.cancelled_at.desc())
    )

    return result.scalars().all()


@router.post("/appointments/{appointment_id}/force-cancel")
async def force_cancel(
    appointment_id: int,
    reason: str,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_user),
):
    if admin.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Admin only")

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
