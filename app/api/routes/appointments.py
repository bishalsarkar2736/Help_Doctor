from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime

from app.db.postgres import get_db
from app.security.jwt import get_current_user
from app.models.user import User
from app.models.appointment import AppointmentStatus

from app.schemas.appointment import AppointmentOut

from app.services.appointment_service import (
    book_appointment,
    get_patient_appointments,
    doctor_update_appointment_status,
    doctor_reschedule_appointment,
    patient_cancel_appointment,
    patient_reschedule_appointment,
    doctor_today_appointments,
    doctor_pending_appointments,
    doctor_confirmed_appointments,
)

router = APIRouter(
    prefix="/appointments",
    tags=["Appointments"],
)


@router.post("/")
async def create_appointment(
    doctor_id: int,
    scheduled_at: datetime,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return await book_appointment(db, user, doctor_id, scheduled_at)


@router.post("/{appointment_id}/confirm")
async def confirm_appointment(
    appointment_id: int,
    db: AsyncSession = Depends(get_db),
    doctor: User = Depends(get_current_user),
):
    return await doctor_update_appointment_status(
        db=db,
        doctor_user=doctor,
        appointment_id=appointment_id,
        new_status=AppointmentStatus.CONFIRMED,
    )


@router.post("/{appointment_id}/cancel")
async def doctor_cancel(
    appointment_id: int,
    db: AsyncSession = Depends(get_db),
    doctor: User = Depends(get_current_user),
):
    return await doctor_update_appointment_status(
        db=db,
        doctor_user=doctor,
        appointment_id=appointment_id,
        new_status=AppointmentStatus.CANCELLED,
    )


@router.get("/own", response_model=list[AppointmentOut])
async def my_appointments(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return await get_patient_appointments(db, user)


# ---------------- PATIENT ----------------

@router.post("/{appointment_id}/cancel-by-patient")
async def patient_cancel(
    appointment_id: int,
    db: AsyncSession = Depends(get_db),
    patient: User = Depends(get_current_user),
):
    return await patient_cancel_appointment(db, patient, appointment_id)


@router.post("/{appointment_id}/reschedule-by-patient")
async def patient_reschedule(
    appointment_id: int,
    new_datetime: datetime,
    db: AsyncSession = Depends(get_db),
    patient: User = Depends(get_current_user),
):
    return await patient_reschedule_appointment(
        db, patient, appointment_id, new_datetime
    )


@router.post("/{appointment_id}/reschedule-by-doctor")
async def doctor_reschedule(
    appointment_id: int,
    new_datetime: datetime,
    db: AsyncSession = Depends(get_db),
    doctor: User = Depends(get_current_user),
):
    return await doctor_reschedule_appointment(
        db=db,
        doctor_user=doctor,
        appointment_id=appointment_id,
        new_datetime=new_datetime,
    )


# ---------------- DOCTOR DASHBOARD ----------------

@router.get("/doctor/today")
async def doctor_today(
    db: AsyncSession = Depends(get_db),
    doctor: User = Depends(get_current_user),
):
    return await doctor_today_appointments(db, doctor)


@router.get("/doctor/pending")
async def doctor_pending(
    db: AsyncSession = Depends(get_db),
    doctor: User = Depends(get_current_user),
):
    return await doctor_pending_appointments(db, doctor)


@router.get("/doctor/confirmed")
async def doctor_confirmed(
    db: AsyncSession = Depends(get_db),
    doctor: User = Depends(get_current_user),
):
    return await doctor_confirmed_appointments(db, doctor)
