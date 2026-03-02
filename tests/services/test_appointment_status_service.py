import pytest
from datetime import datetime, timedelta

from app.models.appointment import Appointment, AppointmentStatus
from app.services.appointment_status_service import (
    confirm_appointment,
    complete_appointment,
)
from app.core.time import UTC
from app.try_except.exceptions import BadRequestError, ForbiddenError
from app.domain.fsm.appointment_transition import transition_appointment


@pytest.mark.asyncio
async def test_doctor_can_confirm_pending_appointment(
    db,
    doctor,         # Doctor model
    patient_user,
):
    appointment = Appointment(
        doctor_id=doctor.id,
        patient_id=patient_user.id,
        scheduled_at=datetime.now(UTC) + timedelta(days=1),
        status=AppointmentStatus.PENDING,
    )
    db.add(appointment)
    await db.commit()
    await db.refresh(appointment)

    updated = await confirm_appointment(
        db=db,
        appointment=appointment,
        doctor=doctor,   # ✅ pass Doctor model
    )

    assert updated.status == AppointmentStatus.CONFIRMED


@pytest.mark.asyncio
async def test_patient_cannot_confirm_appointment(
    db,
    doctor,
    patient_user,
    another_doctor,  # Fixture for a different Doctor
):
    appointment = Appointment(
        doctor_id=doctor.id,
        patient_id=patient_user.id,
        scheduled_at=datetime.now(UTC) + timedelta(days=1),
        status=AppointmentStatus.PENDING,
    )
    db.add(appointment)
    await db.commit()
    await db.refresh(appointment)

    with pytest.raises(ForbiddenError):
        # Passing a doctor who is NOT the owner
        await confirm_appointment(
            db=db,
            appointment=appointment,
            doctor=another_doctor,
        )


@pytest.mark.asyncio
async def test_cannot_confirm_already_confirmed_appointment(
    db,
    doctor,        # Doctor model fixture
    patient_user,
):
    appointment = Appointment(
        doctor_id=doctor.id,
        patient_id=patient_user.id,
        scheduled_at=datetime.now(UTC) + timedelta(days=1),
        status=AppointmentStatus.CONFIRMED,
    )
    db.add(appointment)
    await db.commit()
    await db.refresh(appointment)

    # Must pass Doctor model, not User
    with pytest.raises(BadRequestError):
        await confirm_appointment(
            db=db,
            appointment=appointment,
            doctor=doctor,  # ✅ correct
        )


@pytest.mark.asyncio
async def test_doctor_can_complete_confirmed_appointment(
    db,
    doctor,          # Doctor model
    patient_user,
):
    appointment = Appointment(
        doctor_id=doctor.id,
        patient_id=patient_user.id,
        scheduled_at=datetime.now(UTC) - timedelta(minutes=40),
        status=AppointmentStatus.PENDING,
    )
    db.add(appointment)
    await db.flush()

    # Transition to CONFIRMED first
    await transition_appointment(
        db=db,
        appointment=appointment,
        new_status=AppointmentStatus.CONFIRMED,
        changed_by=doctor.user_id,  # ✅ use doctor.user_id
    )

    await db.flush()
    await db.refresh(appointment)

    updated = await complete_appointment(
        db=db,
        appointment=appointment,
        doctor=doctor,  # ✅ pass Doctor model
    )

    assert updated.status == AppointmentStatus.COMPLETED
    assert updated.completed_at is not None


@pytest.mark.asyncio
async def test_cannot_complete_scheduled_appointment(
    db,
    doctor,
    patient_user,
):
    appointment = Appointment(
        doctor_id=doctor.id,
        patient_id=patient_user.id,
        scheduled_at=datetime.now(UTC) - timedelta(minutes=40),
        status=AppointmentStatus.PENDING,
    )
    db.add(appointment)
    await db.commit()
    await db.refresh(appointment)

    with pytest.raises(BadRequestError):
        await complete_appointment(
            db=db,
            appointment=appointment,
            doctor=doctor,
        )


@pytest.mark.asyncio
async def test_cannot_modify_cancelled_appointment(
    db,
    doctor,
    patient_user,
):
    appointment = Appointment(
        doctor_id=doctor.id,
        patient_id=patient_user.id,
        scheduled_at=datetime.now(UTC) - timedelta(minutes=40),
        status=AppointmentStatus.PENDING,
    )
    db.add(appointment)
    await db.flush()

    # Transition to CANCELLED
    await transition_appointment(
        db=db,
        appointment=appointment,
        new_status=AppointmentStatus.CANCELLED,
        changed_by=doctor.user_id,
    )

    await db.flush()
    await db.refresh(appointment)

    with pytest.raises(BadRequestError):
        await confirm_appointment(
            db=db,
            appointment=appointment,
            doctor=doctor,
        )