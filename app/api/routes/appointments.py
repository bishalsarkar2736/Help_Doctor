from fastapi import APIRouter, Depends, Request, Query
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime

from app.db.postgres import get_db
from app.security.jwt import get_current_user
from app.security.rbac import require_roles

from app.models.user import User, UserRole
from app.models.appointment import AppointmentStatus

from app.schemas.appointment import AppointmentOut, DoctorAppointmentView
from app.try_except.exceptions import BadRequestError
from app.services.appointment_service import (
    book_appointment,
    get_patient_appointments,
    doctor_update_appointment_status,
    doctor_reschedule_appointment,
    patient_cancel_appointment,
    patient_reschedule_appointment,
    doctor_today_appointments,
    doctor_pending_with_patient,
    doctor_confirmed_with_patient,
)
from app.schemas.appointment import AppointmentCreate

from app.services.idempotency_service import (
    get_existing_key,
    store_key,
    save_response,
    create_request_hash,
)
from app.schemas.appointment import AppointmentDetailOut
from app.mappers.appointment_mapper import to_appointment_detail
from app.services.appointment_service import get_appointment_by_id

from app.models.appointment import Appointment
from app.try_except.exceptions import NotFoundError
from app.services.consultation_service import start_consultation




router = APIRouter(
    prefix="/appointments",
    tags=["Appointments"],
)


# ---------------- CREATE APPOINTMENT ----------------

@router.post("/")
async def create_appointment(
    request: Request,
    data: AppointmentCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    
    doctor_id = data.doctor_id
    scheduled_at = data.scheduled_at

    # 🔥 1. GET KEY FROM HEADER
    idempotency_key = request.headers.get("Idempotency-Key")

    if not idempotency_key:
        # fallback (optional)
        appointment = await book_appointment(
            db, user, doctor_id, scheduled_at
        )

        return {
            "appointment_id": appointment.id,
            "doctor_id": doctor_id,
            "scheduled_at": scheduled_at.isoformat(),
            "status": appointment.status.value,
        }

    # 🔥 2. CREATE REQUEST HASH
    request_body = {
        "doctor_id": doctor_id,
        "scheduled_at": scheduled_at.isoformat(),
    }

    request_hash = create_request_hash(request_body)

    # 🔥 3. CHECK EXISTING
    record = await get_existing_key(
        db,
        idempotency_key,
        user.id,
    )

    if record:

        # ❌ BLOCK PAYLOAD MISMATCH
        if record.request_hash != request_hash:
            raise BadRequestError("Idempotency key reused with different request")

        # ✅ RETURN STORED RESPONSE
        if record.response_body:
            return record.response_body

        # ⚠ if exists but no response → continue

    else:
        # 🔥 CREATE LOCK RECORD
        record = await store_key(
            db,
            idempotency_key,
            user.id,
            request_hash,
        )

    # =========================
    # 🔥 BUSINESS LOGIC
    # =========================

    appointment = await book_appointment(
        db,
        user,
        doctor_id,
        scheduled_at,
    )

    # 🔥 4. SAFE RESPONSE (IMPORTANT)
    response = {
        "appointment_id": appointment.id,
        "doctor_id": doctor_id,
        "scheduled_at": scheduled_at.isoformat(),
        "status": appointment.status.value,
    }

    # 🔥 5. SAVE RESPONSE
    await save_response(
        db=db,
        record=record,
        response_body=response,
        status_code=200,
    )

    return response


# ---------------- DOCTOR ACTIONS ----------------

@router.post("/{appointment_id}/confirm",
            response_model=AppointmentDetailOut,
)
async def confirm_appointment(
    appointment_id: int,
    db: AsyncSession = Depends(get_db),
    doctor: User = Depends(require_roles(UserRole.DOCTOR)),
):
    
    appointment =  await doctor_update_appointment_status(
        db=db,
        doctor_user=doctor,
        appointment_id=appointment_id,
        new_status=AppointmentStatus.CONFIRMED,
    )

    return to_appointment_detail(appointment)


@router.post("/{appointment_id}/cancel",
            response_model=AppointmentDetailOut,
)
async def doctor_cancel(
    appointment_id: int,
    db: AsyncSession = Depends(get_db),
    doctor: User = Depends(require_roles(UserRole.DOCTOR)),
):
    appointment =  await doctor_update_appointment_status(
        db=db,
        doctor_user=doctor,
        appointment_id=appointment_id,
        new_status=AppointmentStatus.CANCELLED,
    )
    return to_appointment_detail(appointment)


@router.post("/{appointment_id}/reschedule-by-doctor",
            response_model=AppointmentDetailOut,
)
async def doctor_reschedule(
    appointment_id: int,
    new_datetime: datetime,
    db: AsyncSession = Depends(get_db),
    doctor: User = Depends(require_roles(UserRole.DOCTOR)),
):
    appointment =  await doctor_reschedule_appointment(
        db=db,
        doctor_user=doctor,
        appointment_id=appointment_id,
        new_datetime=new_datetime,
    )
    return to_appointment_detail(appointment)


# ---------------- PATIENT ----------------

@router.get("/own", response_model=list[AppointmentOut])
async def my_appointments(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return await get_patient_appointments(db, user)


@router.get(
    "/{appointment_id}",
    response_model=AppointmentDetailOut,
)
async def get_appointment_detail(
    appointment_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):

    appointment = await get_appointment_by_id(
        db=db,
        appointment_id=appointment_id,
        user=user,
    )

    return to_appointment_detail(appointment)


@router.post("/{appointment_id}/cancel-by-patient",
            response_model=AppointmentDetailOut, 
)
async def patient_cancel(
    appointment_id: int,
    db: AsyncSession = Depends(get_db),
    patient: User = Depends(get_current_user),
):
    appointment =  await patient_cancel_appointment(db, patient, appointment_id)

    return to_appointment_detail(appointment)

@router.post("/{appointment_id}/reschedule-by-patient",
            response_model=AppointmentDetailOut,
)
async def patient_reschedule(
    appointment_id: int,
    new_datetime: datetime,
    db: AsyncSession = Depends(get_db),
    patient: User = Depends(get_current_user),
):
    appointment =  await patient_reschedule_appointment(
        db, patient, appointment_id, new_datetime
    )
    return to_appointment_detail(appointment)


# ---------------- DOCTOR DASHBOARD ----------------

@router.get("/doctor/today",response_model=list[AppointmentDetailOut])
async def doctor_today(
    db: AsyncSession = Depends(get_db),
    doctor: User = Depends(require_roles(UserRole.DOCTOR)),
):
    appointments =  await doctor_today_appointments(db, doctor)
    
    return [
        to_appointment_detail(a)
        for a in appointments
    ]



@router.get("/doctor/pending", response_model=list[DoctorAppointmentView])
async def doctor_pending(
    db: AsyncSession = Depends(get_db),
    doctor: User = Depends(require_roles(UserRole.DOCTOR)),
    limit: int = Query(50, le=100),
    offset: int = Query(0),
):
    rows = await doctor_pending_with_patient(db, doctor, limit, offset)

    return [
        DoctorAppointmentView(
            id=appointment.id,
            scheduled_at=appointment.scheduled_at,
            status=appointment.status.value,
            patient_name=patient.full_name,
            patient_email=patient.email,
            notes=appointment.notes,
        )
        for appointment, patient in rows
    ]


@router.get("/doctor/confirmed", response_model=list[DoctorAppointmentView])
async def doctor_confirmed(
    db: AsyncSession = Depends(get_db),
    doctor: User = Depends(require_roles(UserRole.DOCTOR)),
    limit: int = Query(50, le=100),
    offset: int = Query(0),
):
    rows = await doctor_confirmed_with_patient(db, doctor, limit, offset)

    return [
        DoctorAppointmentView(
            id=appointment.id,
            scheduled_at=appointment.scheduled_at,
            status=appointment.status.value,
            patient_name=patient.full_name,
            patient_email=patient.email,
            notes=appointment.notes,
        )
        for appointment, patient in rows
    ]




@router.post("/{appointment_id}/start-consultation")
async def start_consultation_endpoint(
    appointment_id: int,
    db: AsyncSession = Depends(get_db),
    doctor: User = Depends(require_roles(UserRole.DOCTOR)),
):
    appointment = await db.get(
        Appointment,
        appointment_id,
    )

    if not appointment:
        raise NotFoundError("Appointment not found")

    await start_consultation(
        db=db,
        appointment=appointment,
        doctor_id=doctor.id,
    )

    return {
        "message": "consultation_started"
    }