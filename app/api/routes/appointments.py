from fastapi import APIRouter, Depends, Request, Query
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime,date
from app.db.postgres import get_db
from app.security.jwt import get_current_user
from app.security.rbac import require_roles

from app.models.user import User, UserRole
from app.models.appointment import AppointmentStatus
from sqlalchemy import select

from app.models.doctor import Doctor
from app.schemas.waiting_queue import QueuePositionOut
from app.schemas.appointment import (
    AppointmentOut, 
    DoctorAppointmentView,
    AppointmentSearchOut
)
from app.services.tenant_resolver import resolve_clinic_id
from app.try_except.exceptions import (
    BadRequestError,
    ForbiddenError,
    NotFoundError,
)
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
    get_appointment_by_id
)
from app.schemas.appointment import AppointmentCreate
from app.services.appointment_search_service import search_appointments
from app.services.idempotency_service import (
    get_existing_key,
    store_key,
    save_response,
    create_request_hash,
)
from app.schemas.appointment import AppointmentDetailOut
from app.mappers.appointment_mapper import to_appointment_detail

from app.services.consultation_service import (
    start_consultation,
)
from app.services.appointment_status_service import (
    check_in_patient,
    move_to_waiting,
    complete_appointment,
)
from app.services.pres_doctor_profile_service import get_doctor_profile
from app.services.waiting_queue_service import (
    get_doctor_queue_summary,
    get_patient_position,
    estimate_wait_from_position
)

from app.schemas.waiting_queue import (
    WaitingQueueSummary,
    QueueStatsOut,
)
from app.services.waiting_queue_service import (
    get_queue_stats,
)


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

    # Resolve the patient we are booking for. Patients always book for
    # themselves; only RECEPTIONIST / ADMIN may book on behalf of a patient.
    booking_patient = user
    if data.patient_id is not None and data.patient_id != user.id:
        if user.role not in (UserRole.RECEPTIONIST, UserRole.ADMIN):
            raise ForbiddenError(
                "Only reception or admin can book for another patient"
            )
        booking_patient = await db.get(User, data.patient_id)
        if booking_patient is None or booking_patient.role != UserRole.PATIENT:
            raise NotFoundError("Patient not found")

    # 🔥 1. GET KEY FROM HEADER
    idempotency_key = request.headers.get("Idempotency-Key")

    if not idempotency_key:
        # fallback (optional)
        appointment = await book_appointment(
            db, booking_patient, doctor_id, scheduled_at, booked_by=user
        )

        return {
            "appointment_id": appointment.id,
            "doctor_id": doctor_id,
            "scheduled_at": scheduled_at.isoformat(),
            "status": appointment.status.value,
        }

    # 🔥 2. CREATE REQUEST HASH
    #
    # patient_id is part of the request's identity, not decoration: reception
    # books for different people from one desk. Without it, two bookings that
    # differ only in WHO they are for hash the same, and the second is answered
    # from the first's stored response — no appointment created, and the first
    # patient's appointment id returned for the second. The mismatch guard
    # below exists to catch exactly that and cannot fire on a field the hash
    # does not include.
    request_body = {
        "doctor_id": doctor_id,
        "scheduled_at": scheduled_at.isoformat(),
        "patient_id": booking_patient.id,
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
        booking_patient,
        doctor_id,
        scheduled_at,
        booked_by=user,
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
    "/search",
    response_model=list[AppointmentSearchOut],
)
async def search_appointments_endpoint(
    clinic_id: int,
    patient: str | None = Query(default=None),
    doctor: str | None = Query(default=None),
    status: AppointmentStatus | None = Query(default=None),
    date: date | None = Query(default=None),
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(
        require_roles(
            UserRole.ADMIN,
            UserRole.DOCTOR,
            UserRole.RECEPTIONIST,
        )
    ),
):
    resolved_clinic_id = await resolve_clinic_id(
        db=db,
        user=current_user,
        clinic_id=clinic_id,
    )

    return await search_appointments(
        db=db,
        clinic_id=resolved_clinic_id,
        patient=patient,
        doctor=doctor,
        status=status,
        date=date,
        start_date=start_date,
        end_date=end_date,
        limit=limit,
        offset=offset,
    )


async def _caller_clinic_id(
    db: AsyncSession,
    user: User,
) -> int:
    """The clinic this caller acts inside, taken from the principal.

    Mirrors patients._searcher_clinic_id, and for the same reason: a doctor's
    clinic lives on their Doctor row, while admins and receptionists carry it
    on the user. Reading user.clinic_id for everyone would deny every doctor,
    since the doctor user row does not have it set.

    (The duplication with patients.py is deliberate for now — sharing it means
    moving a private helper into a common module, which is a refactor with a
    wider blast radius than this endpoint.)
    """

    if user.role == UserRole.DOCTOR:

        clinic_id = await db.scalar(
            select(Doctor.clinic_id).where(Doctor.user_id == user.id)
        )

        if clinic_id is None:
            raise ForbiddenError("Doctor is not assigned to a clinic")

        return clinic_id

    if not user.clinic_id:
        raise ForbiddenError("User is not assigned to a clinic")

    return user.clinic_id


@router.get(
    "/queue",
    response_model=WaitingQueueSummary,
)
async def clinic_doctor_queue(
    doctor_id: int = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(
        require_roles(
            UserRole.DOCTOR,
            UserRole.RECEPTIONIST,
            UserRole.ADMIN,
        )
    ),
):
    """One doctor's live queue, for the staff of that doctor's clinic.

    THE TENANT CHECK BELONGS HERE, NOT IN THE SERVICE.

    waiting_queue_service takes a doctor_id and trusts it — every function in
    it filters on doctor_id and status and has no clinic predicate. That was
    safe only while no endpoint let a caller name a doctor. This one does, so
    the relationship is established before delegating:

        caller's clinic -> doctor_id -> Doctor.clinic_id == caller's clinic
                                     -> get_doctor_queue_summary(doctor_id=...)

    A doctor who does not exist and a doctor in another clinic are answered
    identically. Distinguishing them would confirm that a given id is a real
    doctor somewhere else, which is not something a caller outside that clinic
    should learn from a queue lookup.
    """

    caller_clinic_id = await _caller_clinic_id(db, current_user)

    doctor = await db.scalar(
        select(Doctor).where(Doctor.id == doctor_id)
    )

    if doctor is None or doctor.clinic_id != caller_clinic_id:
        raise NotFoundError("Doctor not found")

    return await get_doctor_queue_summary(
        db=db,
        doctor_id=doctor.id,
    )


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
            id=row.id,
            scheduled_at=row.scheduled_at,
            status=row.status.value,
            patient_name=row.patient_name,
            patient_email=row.patient_email,
            notes=row.notes,
        )
        for row in rows
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
            id=row.id,
            scheduled_at=row.scheduled_at,
            status=row.status.value,
            patient_name=row.patient_name,
            patient_email=row.patient_email,
            notes=row.notes,
        )
        for row in rows
    ]



@router.get(
    "/doctor/queue",
    response_model=WaitingQueueSummary,
)
async def doctor_queue(
    db: AsyncSession = Depends(get_db),
    doctor: User = Depends(
        require_roles(UserRole.DOCTOR),
    ),
):
    """
    Return the doctor's live consultation queue.
    """

    doctor_profile = await get_doctor_profile(
        db=db,
        user_id=doctor.id,
    )

    return await get_doctor_queue_summary(
        db=db,
        doctor_id=doctor_profile.id,
    )


@router.get(
    "/doctor/queue/stats",
    response_model=QueueStatsOut,
)
async def doctor_queue_stats(
    db: AsyncSession = Depends(get_db),
    doctor: User = Depends(
        require_roles(UserRole.DOCTOR),
    ),
):
    """
    Return compact statistics for the doctor's live queue.
    """

    doctor_profile = await get_doctor_profile(
        db=db,
        user_id=doctor.id,
    )

    return await get_queue_stats(
        db=db,
        doctor_id=doctor_profile.id,
    )



@router.post(
    "/{appointment_id}/check-in",
    response_model=AppointmentDetailOut,
)
async def check_in(
    appointment_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(
        require_roles(
            UserRole.DOCTOR,
            UserRole.RECEPTIONIST,
            UserRole.ADMIN,
        )
    ),
):
    appointment = await get_appointment_by_id(
        db=db,
        appointment_id=appointment_id,
        user=current_user,
    )

    appointment = await check_in_patient(
        db=db,
        appointment=appointment,
        current_user=current_user,
    )

    await db.flush()
    await db.refresh(appointment)

    return to_appointment_detail(appointment)


@router.post(
    "/{appointment_id}/move-to-waiting",
    response_model=AppointmentDetailOut,
)
async def move_patient_to_waiting(
    appointment_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(
        require_roles(
            UserRole.DOCTOR,
            UserRole.RECEPTIONIST,
            UserRole.ADMIN,
        )
    ),
):
    appointment = await get_appointment_by_id(
        db=db,
        appointment_id=appointment_id,
        user=current_user,
    )

    appointment = await move_to_waiting(
        db=db,
        appointment=appointment,
        current_user=current_user,
    )

    await db.flush()
    await db.refresh(appointment)

    return to_appointment_detail(appointment)



@router.get(
    "/{appointment_id}/queue-position",
    response_model=QueuePositionOut,
)
async def get_queue_position(
    appointment_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    appointment = await get_appointment_by_id(
        db=db,
        appointment_id=appointment_id,
        user=user,
    )

    position = await get_patient_position(
        db=db,
        doctor_id=appointment.doctor_id,
        appointment_id=appointment.id,
    )

    # estimated_wait = await estimate_wait_time(
    #     db=db,
    #     doctor_id=appointment.doctor_id,
    #     appointment_id=appointment.id,
    # )
    estimated_wait = estimate_wait_from_position(position)

    return QueuePositionOut(
        appointment_id=appointment.id,
        patient_name=appointment.patient.full_name or "",
        position=position,
        estimated_wait_minutes=estimated_wait,
    )



@router.post("/{appointment_id}/start-consultation")
async def start_consultation_endpoint(
    appointment_id: int,
    db: AsyncSession = Depends(get_db),
    doctor: User = Depends(require_roles(UserRole.DOCTOR)),
):
    
    appointment = await get_appointment_by_id(
        db=db,
        appointment_id=appointment_id,
        user=doctor,
    )

    doctor_profile = await get_doctor_profile(
        db=db,
        user_id=doctor.id,
    )

    await start_consultation(
        db=db,
        appointment=appointment,
        doctor=doctor_profile,
    )

    return {
        "message": "consultation_started"
    }


@router.post("/{appointment_id}/complete-consultation")
async def complete_consultation_endpoint(
    appointment_id: int,
    db: AsyncSession = Depends(get_db),
    doctor: User = Depends(require_roles(UserRole.DOCTOR)),
):
    appointment = await get_appointment_by_id(
        db=db,
        appointment_id=appointment_id,
        user=doctor,
    )

    doctor_profile = await get_doctor_profile(
        db=db,
        user_id=doctor.id,
    )

    updated_appointment = await complete_appointment(
        db=db,
        appointment=appointment,
        doctor=doctor_profile,
    )

    return to_appointment_detail(updated_appointment)


