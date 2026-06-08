import pytest
from datetime import datetime, timedelta,time
from app.core.time import UTC
from app.services.appointment_service import (
    book_appointment,
    doctor_update_appointment_status,
    patient_cancel_appointment,
)
from app.models.appointment import AppointmentStatus
from zoneinfo import ZoneInfo
from sqlalchemy import select
from app.models.doctor import Doctor
from app.models.doctor_availability import DoctorAvailability
from app.try_except.exceptions import (
    BadRequestError,
    ForbiddenError,
)
from tests.conftest import valid_slot

UTC = ZoneInfo("UTC")

@pytest.mark.asyncio
async def test_book_appointment_invalid_doctor_id(db, patient_user):
    with pytest.raises(BadRequestError):
        await book_appointment(
            db=db,
            patient=patient_user,
            doctor_id=999999,
            scheduled_at=valid_slot(datetime.now(UTC) + timedelta(days=1)),
        )


@pytest.mark.asyncio
async def test_book_appointment_in_past(
    db, patient_user, doctor, doctor_availability
):
    past_time = valid_slot(datetime.now(UTC) - timedelta(days=1))

    with pytest.raises(BadRequestError):
        await book_appointment(
            db=db,
            patient=patient_user,
            doctor_id=doctor.id,
            scheduled_at=past_time,
        )
    


@pytest.mark.asyncio
async def test_double_booking_same_slot_not_allowed(
    db, patient_user,doctor,doctor_availability
):
    time_slot = valid_slot(datetime.now(UTC) + timedelta(days=1))

    await book_appointment(db, patient_user, doctor.id, time_slot)

    with pytest.raises(BadRequestError):
        await book_appointment(db, patient_user, doctor.id, time_slot)


@pytest.mark.asyncio
async def test_doctor_cannot_book_appointment(
    db, doctor_user,doctor
):
    with pytest.raises(ForbiddenError):
        await book_appointment(
            db,
            doctor_user,
            doctor.id,
            valid_slot(datetime.now(UTC) + timedelta(days=1)),
        )


@pytest.mark.asyncio
async def test_doctor_can_confirm_appointment(
    db, doctor_user,doctor, patient_user,doctor_availability
):
    appt = await book_appointment(
        db,
        patient_user,
        doctor.id,
        valid_slot(datetime.now(UTC) + timedelta(days=1)),
    )

    updated = await doctor_update_appointment_status(
        db,
        doctor_user,
        appt.id,
        AppointmentStatus.CONFIRMED,
    )

    assert updated.status == AppointmentStatus.CONFIRMED


@pytest.mark.asyncio
async def test_patient_cancel_confirmed_appointment(
    db, doctor_user,doctor, patient_user,doctor_availability
):
    appt = await book_appointment(
        db,
        patient_user,
        doctor.id,
        valid_slot(datetime.now(UTC) + timedelta(days=1)),
    )

    await doctor_update_appointment_status(
        db,
        doctor_user,
        appt.id,
        AppointmentStatus.CONFIRMED,
    )

    cancelled = await patient_cancel_appointment(
        db,
        patient_user,
        appt.id,
    )

    assert cancelled.status == AppointmentStatus.CANCELLED



@pytest.mark.asyncio
async def test_patient_cannot_cancel_others_appointment(
    db,
    doctor_user,
    doctor,
    doctor_availability,
    patient_user,
    another_patient_user,
):
    # Patient A books an appointment
    appointment = await book_appointment(
        db,
        patient_user,
        doctor.id,
        valid_slot(datetime.now(UTC) + timedelta(days=1)),
    )

    # Patient B tries to cancel Patient A's appointment
    with pytest.raises(ForbiddenError) as exc:
        await patient_cancel_appointment(
            db,
            another_patient_user,
            appointment.id,
        )
   

    


@pytest.mark.asyncio
async def test_cannot_book_outside_doctor_availability(
    db,
    patient_user,
    doctor,
    doctor_user,
):
    """
    Doctor has NO availability created.
    Booking should fail.
    """
    future_time = valid_slot(datetime.now(UTC) + timedelta(days=1))

    with pytest.raises(BadRequestError):
        await book_appointment(
            db,
            patient_user,
            doctor.id,
            future_time,
        )



@pytest.mark.asyncio
async def test_cannot_book_outside_doctor_availability_window(
    db,
    doctor,
    patient_user,
):
    """
    Doctor is available 09:00–12:00.
    Patient tries to book at 15:00.
    This must FAIL.
    """

    # # Resolve Doctor row
    # doctor_result = await db.execute(
    #     select(Doctor).where(Doctor.user_id == doctor_user.id)
    # )
    # doctor = doctor_result.scalar_one()

    # 1️⃣ Create doctor availability: Monday, 09:00–12:00
    availability = DoctorAvailability(
        doctor_id=doctor.id,
        day_of_week=0,  # Monday
        start_time=time(9, 0),
        end_time=time(12, 0),
        is_available=True,
    )

    db.add(availability)
    await db.commit()

    # 2️⃣ Pick a Monday at 15:00 (outside availability)
    booking_time = datetime.now(UTC) + timedelta(
        days=(0 - datetime.now(UTC).weekday()) % 7
    )
    booking_time = booking_time.replace(hour=15, minute=0, second=0, microsecond=0)

    # 3️⃣ Attempt booking → MUST fail
    with pytest.raises(BadRequestError):
        await book_appointment(
            db,
            patient_user,
            doctor.id,
            booking_time,
        )



@pytest.mark.asyncio
async def test_can_book_inside_doctor_availability_window(
    db,
    doctor,
    patient_user,
):
    """
    Doctor is available 09:00–17:00.
    Patient books at 10:00.
    This MUST succeed.
    """

    booking_time = (
        datetime.now(UTC)
        .replace(hour=10, minute=0, second=0, microsecond=0)
        + timedelta(days=1)
    )

    # doctor_result = await db.execute(
    #     select(Doctor).where(Doctor.user_id == doctor_user.id)
    # )
    # doctor = doctor_result.scalar_one()

    availability = DoctorAvailability(
        doctor_id=doctor.id,
        day_of_week=booking_time.weekday(),  # ✅ SAME DAY
        start_time=time(9, 0),
        end_time=time(17, 0),
        is_available=True,
    )

    db.add(availability)
    await db.commit()

    appointment = await book_appointment(
        db,
        patient_user,
        doctor.id,
        booking_time,
    )

    assert appointment is not None


@pytest.mark.asyncio
async def test_cannot_book_overlapping_appointment(
    db,
    doctor,
    doctor_availability,
    patient_user,
    another_patient_user,
):
    """
    Doctor already has an appointment at 10:00.
    Another patient tries to book at 10:00 → MUST fail.
    """

    booking_time = (
        datetime.now(UTC)
        .replace(hour=10, minute=0, second=0, microsecond=0)
        + timedelta(days=1)
    )

    # First appointment (valid)
    await book_appointment(
        db,
        patient_user,
        doctor.id,
        booking_time,
    )

    # Second overlapping appointment
    with pytest.raises(BadRequestError) as exc:
        await book_appointment(
            db,
            another_patient_user,
            doctor.id,
            booking_time,
        )

    
    

@pytest.mark.asyncio
async def test_can_book_non_overlapping_appointment(
    db,
    doctor,
    doctor_availability,
    patient_user,
    another_patient_user,
):
    """
    First appointment at 10:00.
    Second appointment at 10:30 → MUST succeed.
    """

    base_time = (
        datetime.now(UTC)
        .replace(hour=10, minute=0, second=0, microsecond=0)
        + timedelta(days=1)
    )

    await book_appointment(
        db,
        patient_user,
        doctor.id,
        base_time,
    )

    second_time = base_time + timedelta(minutes=30)

    appointment = await book_appointment(
        db,
        another_patient_user,
        doctor.id,
        second_time,
    )

    assert appointment is not None


