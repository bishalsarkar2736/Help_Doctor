
from datetime import datetime, timedelta, timezone

import pytest

from app.models.appointment import Appointment,AppointmentStatus
from app.models.user import User
from app.models.doctor import Doctor
from app.services.appointment_no_show_service import mark_no_show_appointments


@pytest.mark.asyncio
async def test_mark_no_show_appointments(
    db,
    default_clinic,
):
    # Create patient
    patient = User(
        email="patient@test.com",
        hashed_password="x",
        role="PATIENT",
        is_active=True,
    )

    # Create doctor user
    doctor_user = User(
        email="doctor@test.com",
        hashed_password="x",
        role="DOCTOR",
        is_active=True,
    )

    db.add_all([patient, doctor_user])
    await db.flush()

    doctor = Doctor(
        user_id=doctor_user.id,
        clinic_id=default_clinic.id,
        specialization="General",
        experience_years=5,
        bio="Test doctor",
    )

    db.add(doctor)
    await db.flush()

    # Appointment in the past
    appointment = Appointment(
        doctor_id=doctor.id,
        patient_id=patient.id,
        clinic_id=default_clinic.id,
        scheduled_at=datetime.now(timezone.utc) - timedelta(hours=2),
        status="CONFIRMED",
    )

    db.add(appointment)
    await db.commit()

    # Run NO_SHOW job
    count = await mark_no_show_appointments(db)

    assert count == 1

    await db.refresh(appointment)
    assert appointment.status == AppointmentStatus.NO_SHOW
